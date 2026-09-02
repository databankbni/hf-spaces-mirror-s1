"""Operations Research knowledge corpus with multi-layer representations."""

from __future__ import annotations

from ragkit.models import Chunk

PRODUCT = "OR Knowledge Copilot"
SYNONYMS = {
    "vrp": ["vehicle routing", "cvrp", "delivery routes", "time windows"],
    "fjssp": ["flexible job shop", "makespan", "cp-sat", "job-shop"],
    "lot sizing": ["inventory", "setup cost", "holding cost", "production planning"],
    "pyomo": ["python milp", "concrete model", "solver"],
    "unit commitment": ["generator dispatch", "spinning reserve", "power"],
}

PROBLEMS = [
    {
        "doc_id": "or-vrp-nethorizon",
        "title": "NetHorizon last-mile CVRPTW",
        "domain": "Routing",
        "solver_name": "ortools",
        "difficulty": "hard",
        "nl": (
            "NetHorizon last-mile CVRPTW serves 50 customers from a single depot with six vehicles. "
            "Each vehicle has capacity 200 kilograms. Customer time windows sit between 08:00 and 18:00. "
            "The planner must minimize total distance plus a lateness penalty of 4.5 per minute."
        ),
        "math": (
            "Minimize sum_k sum_i sum_j c_ij x_ijk + 4.5 sum_i max(0, a_i - l_i). "
            "Subject to each customer visited once, vehicle load <= 200, and a_i in [e_i, l_i] with e_i>=08:00 and l_i<=18:00."
        ),
        "pyomo": (
            "from pyomo.environ import *\n"
            "model = ConcreteModel('NetHorizon_CVRPTW')\n"
            "model.N = RangeSet(0, 50)\n"
            "model.K = RangeSet(1, 6)\n"
            "model.x = Var(model.N, model.N, model.K, domain=Binary)\n"
            "model.capacity = Param(initialize=200)\n"
            "# objective: distance + 4.5 * lateness"
        ),
        "minizinc": (
            "% NetHorizon CVRPTW\nint: n = 50;\nint: vehicles = 6;\nint: capacity = 200;\n"
            "array[1..n] of int: demand;\nsolve minimize total_distance + 45*lateness_tenths;"
        ),
        "solver": (
            "Solver: OR-Tools routing CP-SAT hybrid. Status: feasible. "
            "Best objective 1842.6 km equivalent. Runtime 38.4 seconds. "
            "Six routes, max load 196 kg, two customers with 7 minutes slack."
        ),
        "explain": (
            "The binding constraints are vehicle capacity 200 kg and the 18:00 close of the city hub. "
            "OR-Tools is preferred over a pure MIP because the 50-customer time-window graph is too large for a compact MTZ formulation. "
            "If demand grows above 80 customers, switch to ALNS with the same capacity and penalty."
        ),
    },
    {
        "doc_id": "or-fjssp-lineb",
        "title": "Line-B flexible job-shop",
        "domain": "Scheduling",
        "solver_name": "cp_sat",
        "difficulty": "hard",
        "nl": (
            "Line-B FJSSP has 20 jobs and 5 machines. Each operation may run on two eligible machines. "
            "The production target is a makespan bound of 312 minutes. Dispatching with SPT exceeds 340 minutes."
        ),
        "math": (
            "Minimize Cmax. For each operation o, sum_m y_om = 1 for eligible machines. "
            "No-overlap on each machine. Precedence start(o2) >= start(o1)+p_o1m. Cmax >= start+p for all last operations."
        ),
        "pyomo": (
            "# Line-B is solved with CP-SAT, not Pyomo MIP, because disjunctive machine constraints explode. "
            "Use ortools.sat.python.cp_model.CpModel with interval variables and AddNoOverlap."
        ),
        "minizinc": (
            "include \"cumulative.mzn\";\nint: jobs = 20;\nint: machines = 5;\nvar 0..400: makespan;\n"
            "constraint makespan <= 312;\nsolve minimize makespan;"
        ),
        "solver": (
            "Solver: Google CP-SAT. Status: optimal. Makespan 308 minutes, 4 minutes under the 312 bound. "
            "Runtime 12.1 seconds. Machine 3 is the bottleneck with 96 percent utilization."
        ),
        "explain": (
            "CP-SAT finds a 308-minute calendar because it reasons over intervals rather than big-M disjunctions. "
            "Machine 3 is binding. Adding a sixth eligible machine for coating operations is the first capacity lever."
        ),
    },
    {
        "doc_id": "or-lotsizing-dc14",
        "title": "DC-14 multi-item lot sizing",
        "domain": "Inventory",
        "solver_name": "highs",
        "difficulty": "medium",
        "nl": (
            "DC-14 plans 12 SKUs over 8 weeks. Holding cost is 1.20 per unit-week. Setup cost is 450 per changeover. "
            "Week-3 demand spike is 1800 units of SKU-NH442. HiGHS is the default open solver."
        ),
        "math": (
            "Minimize sum_t (1.20 I_t + 450 y_t + produce_cost x_t). "
            "Inventory balance I_t = I_{t-1}+x_t-d_t. x_t <= M y_t. I_t, x_t >= 0, y_t binary."
        ),
        "pyomo": (
            "from pyomo.environ import *\nmodel = ConcreteModel('DC14_LotSizing')\n"
            "model.T = RangeSet(1, 8)\nmodel.P = Set(initialize=['SKU-NH442'])\n"
            "model.hold = Param(initialize=1.20)\nmodel.setup = Param(initialize=450)\n"
            "model.y = Var(model.P, model.T, domain=Binary)"
        ),
        "minizinc": (
            "float: hold = 1.20; float: setup = 450;\narray[1..8] of float: demand;\n"
            "var 0.0..10000.0: inventory;\nsolve minimize hold*inventory + setup*n_setups;"
        ),
        "solver": (
            "Solver: HiGHS. Status: optimal. Objective 18640.0. Four setups, inventory peak 420 units after week 3. Runtime 0.84 seconds."
        ),
        "explain": (
            "Four setups beat weekly changeovers because the 450 setup dwarfs 1.20 holding. "
            "SKU-NH442 should be built in week 2 and week 3 only. If setup falls below 180, weekly production becomes optimal."
        ),
    },
    {
        "doc_id": "or-knapsack-capex",
        "title": "Capex project knapsack",
        "domain": "Portfolio",
        "solver_name": "mip",
        "difficulty": "easy",
        "nl": (
            "Select a subset of 12 plant projects under a shared capex budget of 2.4 million. "
            "Project Gamma cannot be chosen with Project Delta (mutual exclusion). Maximize NPV."
        ),
        "math": (
            "Maximize sum_i npv_i z_i. sum_i cost_i z_i <= 2.4e6. z_gamma + z_delta <= 1. z binary."
        ),
        "pyomo": (
            "model = ConcreteModel('CapexKnapsack')\nmodel.I = RangeSet(1, 12)\n"
            "model.z = Var(model.I, domain=Binary)\nmodel.budget = Param(initialize=2400000)\n"
            "model.conflict = Constraint(expr=model.z[3] + model.z[4] <= 1)"
        ),
        "minizinc": (
            "int: n = 12; int: budget = 2400000;\narray[1..n] of int: cost;\narray[1..n] of int: npv;\n"
            "array[1..n] of var bool: z;\nconstraint z[3] /\\ z[4] = false;\nsolve maximize sum(i in 1..n)(npv[i]*z[i]);"
        ),
        "solver": (
            "Solver: CBC MIP. Status: optimal. NPV 3.18 million. Seven projects selected. Gamma chosen, Delta rejected. Runtime 0.05 seconds."
        ),
        "explain": (
            "The 2.4 million budget is binding. The Gamma/Delta exclusion is active: Gamma has higher NPV per dollar. "
            "A 100k budget increase would add Project Iota, not Delta."
        ),
    },
    {
        "doc_id": "or-pmedian-network",
        "title": "Eight-DC p-median network",
        "domain": "Facility Location",
        "solver_name": "mip",
        "difficulty": "medium",
        "nl": (
            "Locate 8 distribution centers among 40 candidate sites to serve 120 stores. "
            "Service radius target is 45 kilometers. Unmet demand is forbidden."
        ),
        "math": (
            "Minimize sum_i sum_j d_ij x_ij. sum_j y_j = 8. sum_j x_ij = 1 for all stores i. x_ij <= y_j."
        ),
        "pyomo": (
            "model = ConcreteModel('PMedian8')\nmodel.p = Param(initialize=8)\n"
            "model.y = Var(model.Sites, domain=Binary)\nmodel.open_limit = Constraint(expr=sum(model.y[s] for s in model.Sites)==8)"
        ),
        "minizinc": (
            "int: p = 8; int: sites = 40; int: stores = 120;\narray[1..sites] of var bool: open;\n"
            "constraint sum(open) = p;\nsolve minimize total_distance;"
        ),
        "solver": (
            "Solver: SCIP. Status: optimal. Mean distance 28.6 km. All stores within 45 km. Runtime 6.7 seconds."
        ),
        "explain": (
            "p=8 is the smallest count that keeps every store inside 45 km. Closing any of the coastal DCs violates the radius."
        ),
    },
    {
        "doc_id": "or-uc-gridwest",
        "title": "GridWest 24-hour unit commitment",
        "domain": "Energy",
        "solver_name": "mip",
        "difficulty": "hard",
        "nl": (
            "GridWest unit commitment covers 24 hours with 6 thermal generators. Spinning reserve must stay at 12 percent of hourly load. "
            "Minimum up time is 3 hours. Generator G4 is a slow-start steam unit."
        ),
        "math": (
            "Minimize sum_g sum_t (startup_g v_gt + noload_g u_gt + fuel_g p_gt). "
            "Load balance, reserve >= 0.12 load_t, min up 3 hours, ramp limits."
        ),
        "pyomo": (
            "model = ConcreteModel('GridWest_UC')\nmodel.G = RangeSet(1, 6)\nmodel.T = RangeSet(1, 24)\n"
            "model.u = Var(model.G, model.T, domain=Binary)\nmodel.reserve_frac = Param(initialize=0.12)"
        ),
        "minizinc": (
            "int: G = 6; int: T = 24; float: reserve = 0.12;\narray[1..G,1..T] of var bool: on;\nsolve minimize fuel + startup;"
        ),
        "solver": (
            "Solver: Gurobi-compatible MIP. Status: optimal. Cost 412750. G4 stays on from hour 6 to 22. Runtime 3.9 seconds."
        ),
        "explain": (
            "The 12 percent reserve and G4 min-up time force G4 online before the evening peak. "
            "A fast-start aeroderivative in slot G7 would cut cost more than relaxing reserve to 10 percent."
        ),
    },
    {
        "doc_id": "or-binpack-mdf",
        "title": "MDF panel bin packing",
        "domain": "Packing",
        "solver_name": "cp_sat",
        "difficulty": "medium",
        "nl": (
            "Cut 86 rectangular parts from 2800x2070 mm MDF sheets with 3.2 mm kerf. Rotation by 90 degrees is allowed. "
            "The nesting target is at most 17 sheets."
        ),
        "math": (
            "Assign each part to a sheet and coordinates (x,y) with no overlap inflated by 3.2 mm kerf. Minimize number of sheets, upper bound 17."
        ),
        "pyomo": (
            "# Geometry packing is a poor MIP. Use CP-SAT 2D no-overlap or a dedicated nester. "
            "Kerf 3.2 mm is added to part width and height before placement."
        ),
        "minizinc": (
            "int: kerf = 32; % tenths of mm\nint: sheets_ub = 17;\nconstraint no_overlap_2d(x, dx, y, dy);\nsolve minimize n_sheets;"
        ),
        "solver": (
            "Solver: CP-SAT geometry. Status: feasible. 16 sheets used, 91.4 percent average utilization. Runtime 22 seconds."
        ),
        "explain": (
            "Kerf 3.2 mm is the hidden waste driver. Sixteen sheets beat the 17-sheet target. Grain-sensitive parts that cannot rotate need a second pass."
        ),
    },
    {
        "doc_id": "or-staff-roster",
        "title": "Three-shift staff rostering",
        "domain": "Assignment",
        "solver_name": "cp_sat",
        "difficulty": "medium",
        "nl": (
            "Roster 42 technicians across three shifts for 14 days. Maximum consecutive nights is 3. "
            "Each shift needs 9 on-site technicians plus 2 on-call."
        ),
        "math": (
            "Assign binary x_employee,day,shift. Cover >= 9+2. Consecutive night shifts <= 3. Rest after nights >= 24 hours."
        ),
        "pyomo": (
            "model = ConcreteModel('Roster14')\nmodel.E = RangeSet(1, 42)\nmodel.D = RangeSet(1, 14)\n"
            "model.S = Set(initialize=['day','swing','night'])\nmodel.cover = Param(initialize=11)"
        ),
        "minizinc": (
            "include \"global_cardinality.mzn\";\nint: staff = 42;\nint: days = 14;\nconstraint max_nights <= 3;\nsolve satisfy;"
        ),
        "solver": (
            "Solver: CP-SAT. Status: feasible. All cover constraints met. Night-load Gini 0.08. Runtime 2.2 seconds."
        ),
        "explain": (
            "The 3-night cap, not headcount, is binding. Hiring two extra technicians would barely help; relaxing nights to 4 would."
        ),
    },
]


def build_chunks() -> list[Chunk]:
    chunks: list[Chunk] = []
    layers = [
        ("natural_language", "nl", 1),
        ("mathematical_formulation", "math", 2),
        ("pyomo_code", "pyomo", 3),
        ("minizinc_code", "minizinc", 4),
        ("solver_output", "solver", 5),
        ("explanation", "explain", 6),
    ]
    for problem in PROBLEMS:
        for paragraph, (layer, key, page) in enumerate(layers, start=1):
            chunks.append(
                Chunk(
                    chunk_id=f"{problem['doc_id']}::{layer}",
                    doc_id=problem["doc_id"],
                    doc_title=problem["title"],
                    text=str(problem[key]),
                    section=layer.replace("_", " ").title(),
                    page=page,
                    paragraph=paragraph,
                    parent_id=problem["doc_id"],
                    layer=layer,
                    modality="code" if "code" in layer else ("math" if layer.startswith("math") else "text"),
                    metadata={
                        "domain": problem["domain"],
                        "solver": problem["solver_name"],
                        "difficulty": problem["difficulty"],
                    },
                )
            )
    return chunks


def qa_pairs() -> list[dict]:
    return [
        {
            "id": "q1",
            "question": "What vehicle capacity is used in the NetHorizon last-mile CVRPTW?",
            "expected_doc_id": "or-vrp-nethorizon",
            "expected_keywords": ["200"],
        },
        {
            "id": "q2",
            "question": "Which solver should I use for NetHorizon 50-customer time windows?",
            "expected_doc_id": "or-vrp-nethorizon",
            "expected_keywords": ["OR-Tools", "ortools"],
        },
        {
            "id": "q3",
            "question": "What makespan did CP-SAT reach on Line-B FJSSP versus the 312 minute bound?",
            "expected_doc_id": "or-fjssp-lineb",
            "expected_keywords": ["308"],
        },
        {
            "id": "q4",
            "question": "What is the holding cost and setup cost in DC-14 lot sizing?",
            "expected_doc_id": "or-lotsizing-dc14",
            "expected_keywords": ["1.20", "450"],
        },
        {
            "id": "q5",
            "question": "How should Pyomo represent SKU-NH442 lot sizing at DC-14?",
            "expected_doc_id": "or-lotsizing-dc14",
            "expected_keywords": ["SKU-NH442", "1.20"],
        },
        {
            "id": "q6",
            "question": "What is the capex budget and conflict in the project knapsack?",
            "expected_doc_id": "or-knapsack-capex",
            "expected_keywords": ["2.4", "Gamma"],
        },
        {
            "id": "q7",
            "question": "How many distribution centers are opened in the p-median network and what radius is required?",
            "expected_doc_id": "or-pmedian-network",
            "expected_keywords": ["8", "45"],
        },
        {
            "id": "q8",
            "question": "What spinning reserve does GridWest unit commitment enforce?",
            "expected_doc_id": "or-uc-gridwest",
            "expected_keywords": ["12"],
        },
        {
            "id": "q9",
            "question": "Give MiniZinc for GridWest with 6 generators and 24 hours.",
            "expected_doc_id": "or-uc-gridwest",
            "expected_keywords": ["0.12", "24"],
        },
        {
            "id": "q10",
            "question": "What kerf and sheet limit apply to the MDF panel packing problem?",
            "expected_doc_id": "or-binpack-mdf",
            "expected_keywords": ["3.2", "17"],
        },
        {
            "id": "q11",
            "question": "What is the maximum consecutive night shifts in the 42-technician roster?",
            "expected_doc_id": "or-staff-roster",
            "expected_keywords": ["3"],
        },
        {
            "id": "q12",
            "question": "Why is CP-SAT preferred over Pyomo MIP for Line-B flexible job-shop?",
            "expected_doc_id": "or-fjssp-lineb",
            "expected_keywords": ["disjunctive", "interval", "CP-SAT"],
        },
        {
            "id": "q13",
            "question": "What is the Bitcoin mining difficulty this week?",
            "expected_doc_id": "",
            "expected_keywords": [],
            "expect_abstain": True,
        },
        {
            "id": "q14",
            "question": "Who won the 1998 World Cup?",
            "expected_doc_id": "",
            "expected_keywords": [],
            "expect_abstain": True,
        },
        {
            "id": "q15",
            "question": "Write a recipe for chocolate cake.",
            "expected_doc_id": "",
            "expected_keywords": [],
            "expect_abstain": True,
        },
    ]


def router(question: str) -> tuple[str, dict]:
    q = question.lower()
    boosts: dict[str, float] = {}
    if any(w in q for w in ("pyomo", "python", "concrete model")):
        boosts["pyomo_code"] = 1.35
        return "code", {"layer_boosts": boosts}
    if any(w in q for w in ("minizinc", "mzn")):
        boosts["minizinc_code"] = 1.35
        return "code", {"layer_boosts": boosts}
    if any(w in q for w in ("formulation", "minimize", "constraint", "subject to")):
        boosts["mathematical_formulation"] = 1.30
        return "math", {"layer_boosts": boosts}
    if any(w in q for w in ("solver", "runtime", "status", "objective")):
        boosts["solver_output"] = 1.30
        return "solver", {"layer_boosts": boosts}
    if any(w in q for w in ("why", "prefer", "explain", "binding")):
        boosts["explanation"] = 1.25
        return "explain", {"layer_boosts": boosts}
    return "document", {"layer_boosts": boosts}
