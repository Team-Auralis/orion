import asyncio
import json
import os
import signal

import nats

# Ponytail: In-memory set for consumer idempotency scaffold. 
# Production should use Redis or a dedicated worker DB.
processed_events = set()

async def message_handler(msg):
    subject = msg.subject
    data = msg.data.decode()
    
    try:
        event = json.loads(data)
        event_id = event.get('event_id')
        
        # 1. Consumer Idempotency Check
        if event_id in processed_events:
            print(f"Skipping already processed event: {event_id}")
            return
            
        print(f"Processing incident: {event.get('incident_id')} of type {event.get('incident_type')}")
        
        # TODO: Worker Logic (e.g., notify responder dashboard, trigger AI routing)
        await asyncio.sleep(0.5) # Simulate work
        
        # 2. Record event processed
        processed_events.add(event_id)
        print(f"Successfully processed event: {event_id}")
        
    except json.JSONDecodeError:
        print("Failed to decode message data as JSON.")

async def main():
    nats_url = os.environ.get("NATS_URL", "nats://localhost:4222")
    nc = nats.NATS()
    
    try:
        await nc.connect(nats_url)
        print(f"Connected to NATS at {nats_url}")
    except Exception as e:
        print(f"Error connecting to NATS: {e}")
        return

    sub = await nc.subscribe("incident.created", cb=message_handler)
    print("Listening for 'incident.created' events...")

    stop_event = asyncio.Event()

    def signal_handler():
        print("Shutting down worker...")
        stop_event.set()

    loop = asyncio.get_event_loop()
    try:
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, signal_handler)
    except NotImplementedError:
        pass

    await stop_event.wait()
    
    await sub.unsubscribe()
    await nc.drain()

if __name__ == '__main__':
    asyncio.run(main())
