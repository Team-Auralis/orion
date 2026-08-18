package orion.authz

default allow = false

# Helpers
is_authenticated {
    input.subject != null
    input.subject != ""
}

is_operator {
    input.role == "operator"
}

is_citizen {
    input.role == "citizen"
}

# Rule 1: Anyone authenticated can create an SOS incident
allow {
    is_authenticated
    input.action == "incident:create"
    input.resource == "incident"
    input.incident_type == "SOS"
}

# Rule 2: Operators have access to the admin dashboard
allow {
    is_authenticated
    is_operator
    input.action == "dashboard:view"
    input.resource == "admin"
}

# (The negative path / deny for citizen accessing admin is implicitly handled by default allow = false, 
# but we can explicitly deny it or just let the default block it. The prompt's requirement is that a citizen is denied).
