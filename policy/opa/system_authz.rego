package system.authz
import rego.v1

default allow = false

# Allow anyone to evaluate policies (POST to /v1/data/...)
allow if {
    input.method == "POST"
    input.path[0] == "v1"
    input.path[1] == "data"
}

# Allow anyone to read policies (GET)
allow if {
    input.method == "GET"
}
