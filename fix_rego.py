import re

with open('policy/opa/policy.rego', 'r') as f:
    content = f.read()

rule_2 = '''# Rule 2: Operators have access to the admin dashboard
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
}'''

content = content.replace('''# Rule 2: Operators have access to the admin dashboard
allow if {
    is_authenticated
    is_operator
    input.action == "dashboard:view"
    input.resource == "admin"
}''', rule_2)

with open('policy/opa/policy.rego', 'w') as f:
    f.write(content)
