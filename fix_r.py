import re

with open('apps/api/main.py', 'r') as f:
    content = f.read()

# R-07: Location NaN
content = content.replace('class Location(BaseModel):\n    latitude: float\n    longitude: float',
'''class Location(BaseModel):\n    latitude: float\n    longitude: float\n\n    class Config:\n        allow_inf_nan = False''')

# R-02: Redis error handling
content = content.replace('def is_circuit_open(service_name: str) -> bool:\n    if not redis_client: return False\n    return redis_client.get(f"circuit_open:{service_name}") == "1"',
'''def is_circuit_open(service_name: str) -> bool:\n    if not redis_client: return False\n    try:\n        return redis_client.get(f"circuit_open:{service_name}") == "1"\n    except Exception:\n        return False''')

content = content.replace('failures = redis_client.incr("circuit_failures:KEYCLOAK")\n            if failures >= 5:\n                redis_client.setex("circuit_open:KEYCLOAK", 30, "1")',
'''try:\n                failures = redis_client.incr("circuit_failures:KEYCLOAK")\n                if failures >= 5:\n                    redis_client.setex("circuit_open:KEYCLOAK", 30, "1")\n            except Exception:\n                pass''')

content = content.replace('if redis_client: redis_client.delete("circuit_failures:KEYCLOAK")',
'''if redis_client:\n            try:\n                redis_client.delete("circuit_failures:KEYCLOAK")\n            except Exception:\n                pass''')

# R-01: Phoenix Fallback
content = content.replace('        db.commit()\n    except Exception as e:',
'''        db.commit()
    except sqlalchemy.exc.IntegrityError as e:
        db.rollback()
        if namespaced_key:
            cached = db.query(IdempotencyKey).filter(IdempotencyKey.key == namespaced_key).first()
            if cached:
                return json.loads(cached.response_body)
        raise HTTPException(status_code=409, detail="Conflict")
    except sqlalchemy.exc.OperationalError as e:''')

content = content.replace('import sqlalchemy', 'import sqlalchemy')
if 'import sqlalchemy' not in content:
    content = content.replace('from sqlalchemy.orm import Session', 'from sqlalchemy.orm import Session\nimport sqlalchemy\nimport sqlalchemy.exc')

# R-03: Status outbox
status_func_orig = '''    # Publish to NATS first (Event Sourcing)
    if nc.is_connected:
        try:
            js = nc.jetstream()
            await js.publish("incident.status_changed", json.dumps(event).encode())
        except Exception as e:
            print(f"Failed to publish to JetStream: {e}")
            await nc.publish("incident.status_changed", json.dumps(event).encode())
    
    # Note: We don't update the DB here! The Worker will process the event and 
    # apply the CRDT logic to update the Read View in Postgres.
    
    return {"message": "Status update event accepted", "event_id": event["event_id"]}'''

status_func_new = '''    # R-03: Route status updates through the outbox
    outbox_event = OutboxEvent(
        id=event["event_id"],
        topic="incident.status_changed",
        payload=json.dumps(event),
        headers=json.dumps({"X-Correlation-ID": f"req-{uuid.uuid4().hex[:6]}"})
    )
    db.add(outbox_event)
    db.commit()
    return {"message": "Status update event accepted", "event_id": event["event_id"]}'''

content = content.replace(status_func_orig, status_func_new)

with open('apps/api/main.py', 'w') as f:
    f.write(content)
