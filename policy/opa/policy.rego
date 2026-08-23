package orion.authz
import rego.v1
default allow = false

# Helpers
is_authenticated if {
    input.subject != null
    input.subject != ""
}

is_operator if {
    input.role == "operator"
}

is_citizen if {
    input.role == "citizen"
}

# Rule 1: Anyone authenticated can create an SOS incident
allow if {
    is_authenticated
    input.action == "incident:create"
    input.resource == "incident"
    input.incident_type == "SOS"
}

# Rule 2: Operators have access to the admin dashboard
allow if {
    is_authenticated
    is_operator
    input.action == "dashboard:view"
    input.resource == "admin"
}

# Rule 2b: Operators can view assets (R-05 fix)
allow if {
    is_authenticated
    is_operator
    input.action == "dashboard:view"
    input.resource == "assets"
}

# Rule 3: Operators can update incidents
allow if {
    is_authenticated
    is_operator
    input.action == "incident:update"
    input.resource == "incident"
}

# Rule 4: Operators manage the HITL dispatch queue (P1.5-009/P1.5-010)
allow if {
    is_authenticated
    is_operator
    input.action == "dispatch:read"
    input.resource == "dispatch_recommendation"
}

allow if {
    is_authenticated
    is_operator
    input.action == "dispatch:action"
    input.resource == "dispatch_recommendation"
}

allow if {
    is_authenticated
    is_operator
    input.action == "asset:update"
    input.resource == "asset"
}

# Rule 5: Operators control the closed pilot constraints (P1.5-016)
allow if {
    is_authenticated
    is_operator
    input.action == "pilot:status"
    input.resource == "pilot"
}

allow if {
    is_authenticated
    is_operator
    input.action == "pilot:suspend"
    input.resource == "pilot"
}

allow if {
    is_authenticated
    is_operator
    input.action == "pilot:resume"
    input.resource == "pilot"
}

# (The negative path / deny for citizen accessing admin is implicitly handled by default allow = false, 
# but we can explicitly deny it or just let the default block it. The prompt's requirement is that a citizen is denied).
