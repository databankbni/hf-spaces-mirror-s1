from main import fuzzy_match
from database import get_all_dropdowns

dropdowns = get_all_dropdowns()
options = dropdowns.get("Company", [])

print("All Company Options:")
for opt in options:
    print(f" - {opt}")

print("\n--- Test Matches ---")
print("Match for 'Apex Engineering Ltd.':", repr(fuzzy_match("Apex Engineering Ltd.", options)))
print("Match for 'Apex Engineering':", repr(fuzzy_match("Apex Engineering", options)))
print("Match for 'Apex':", repr(fuzzy_match("Apex", options)))
print("Match for 'Apex limited':", repr(fuzzy_match("Apex limited", options)))
print("Match for '':", repr(fuzzy_match("", options)))
