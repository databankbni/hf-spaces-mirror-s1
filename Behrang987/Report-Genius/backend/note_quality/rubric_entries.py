"""Verbatim practice rubric texts, keyed for :mod:`backend.note_quality.rubric`.

Do not tidy these strings. They are the only standard Stage B is allowed to apply.
"""

from __future__ import annotations

# review sub-topic id -> (source-document heading, verbatim rubric)
ENTRIES: dict[str, tuple[str, str]] = {}


def _put(code: str, label: str, text: str) -> None:
    ENTRIES[code] = (label, text.strip() + "\n")


_put(
    "chimney_stacks",
    "Chimney Stacks",
    """**GREEN – Sufficient information**

Green if the site notes provide sufficient information to understand the chimney stack's general construction/form and provide a meaningful inspection assessment of its visible condition.

Where defects or concerns are identified, the notes should provide sufficient information to understand the nature of the issue and, where relevant, its implication, repair, maintenance or further action.

Relevant information may include:

* Construction/material
* General condition
* Pointing/weathering
* Flashings
* Pots
* Stability/movement
* Deterioration or defects
* Inspection limitations
* Repair/maintenance recommendations

Not every item needs to be mentioned. The assessment should be based on whether the combined information provides a meaningful inspection picture of the chimney stack.

**YELLOW – Limited information**

Yellow if the chimney stack is referred to and some relevant information is provided, but the notes do not provide enough meaningful inspection information to meet the Green benchmark.

Example Yellow:
“Chimney stack is of brick construction.”

**RED – No information**

Red if no meaningful information relating to the chimney stack can be identified in the site notes.""",
)

_put(
    "roof_coverings",
    "Roof Coverings",
    """**GREEN – Sufficient information**

Green if the notes provide sufficient information to understand the general roof form/covering and provide a meaningful assessment of its visible condition.

Where defects are identified, there should be sufficient information to understand the nature of the defect and, where relevant, its implication or required action.

Relevant information may include:

* Roof type/form
* Covering material
* General condition
* Missing, slipped or damaged coverings
* Moss/lichen or vegetation
* Weathering
* Sagging/distortion
* Flashings or valleys where relevant
* Previous repairs
* Inspection limitations
* Repair/maintenance recommendations

Not every item needs to be mentioned.

**YELLOW – Limited information**

Yellow if the roof is identified or partially described but meaningful condition information is insufficient.

Example Yellow:
“Pitched roof covered with concrete tiles.”

**RED – No information**

Red if no meaningful information relating to the roof coverings can be identified.""",
)

_put(
    "rainwater_pipes_gutters",
    "Rainwater Pipes & Gutters",
    """**GREEN – Sufficient information**

Green if the notes provide sufficient information to identify the general rainwater disposal arrangements and provide a meaningful assessment of their visible condition or performance.

Relevant information may include:

* Material/type
* Gutters/downpipes
* Alignment
* Leaks/staining
* Blockages
* Corrosion/deterioration
* Joints
* Discharge arrangements
* General condition
* Required repair or maintenance

Not every item needs to be mentioned.

**YELLOW – Limited information**

Yellow if rainwater fittings are identified but there is insufficient meaningful information regarding their condition, performance or relevant observations.

Example Yellow:
“Plastic gutters and downpipes.”

**RED – No information**

Red if no meaningful information relating to rainwater fittings can be identified.""",
)

_put(
    "main_walls",
    "Main Walls",
    """**GREEN – Sufficient information**

Green if the notes provide sufficient information to understand the apparent construction or external finish of the main walls and provide a meaningful assessment of their visible condition.

Where defects or concerns are present, sufficient information should be available to understand their nature and, where relevant, their significance or required action.

Relevant information may include:

* Construction
* Material/finish
* General condition
* Cracking
* Structural movement
* Damp-related observations
* Pointing
* Render
* External ground levels
* Damp-proof course where visible or referred to
* Weathering/deterioration
* Inspection limitations
* Recommendations

Not every item needs to be mentioned.

**YELLOW – Limited information**

Yellow if the walls are identified or their construction/material is described, but there is insufficient meaningful inspection or condition information.

Example Yellow:
“External walls are of brick construction.”

**RED – No information**

Red if no meaningful information relating to the main walls can be identified.""",
)

_put(
    "windows",
    "Windows",
    """**GREEN – Sufficient information**

Green if the notes provide sufficient information to understand the general window type and provide a meaningful assessment of their visible condition or operation.

Relevant information may include:

* Frame material
* Glazing type
* General condition
* Operation
* Failed sealed units or misting
* Rot/deterioration
* Weather seals
* Security
* Damage
* Repair/maintenance requirements

Not every item needs to be mentioned and not every individual window needs to be described where representative observations provide a sufficient overall assessment.

**YELLOW – Limited information**

Yellow if the window type/material is identified but meaningful information regarding condition or operation is insufficient.

Example Yellow:
“uPVC double-glazed windows.”

**RED – No information**

Red if no meaningful information relating to the windows can be identified.""",
)

_put(
    "outside_doors",
    "Outside Doors",
    """**GREEN – Sufficient information**

Green if the notes provide sufficient information to identify the general type of external doors and provide a meaningful assessment of their visible condition, operation or security.

Relevant information may include:

* Material/type
* Glazing
* General condition
* Operation
* Security
* Weather seals
* Alignment
* Deterioration/damage
* Rot
* Repair/maintenance requirements

Not every item needs to be mentioned.

**YELLOW – Limited information**

Yellow if an external door is identified or described but insufficient information regarding condition, operation or other meaningful inspection findings is provided.

Example Yellow:
“Timber front entrance door.”

**RED – No information**

Red if no meaningful information relating to external doors can be identified.""",
)

_put(
    "conservatory_porches",
    "Conservatory and porches",
    """**GREEN – Sufficient information**

Green if the notes provide sufficient information to establish whether a conservatory and/or porch is present and, where present, provide a meaningful assessment of its general construction and visible condition.

Where defects or concerns are identified, the notes should provide sufficient information to understand the nature of the issue and, where relevant, its implication or required action.

Relevant information may include:

* Presence/absence
* General construction
* Roof
* Glazing
* Walls/framework
* Doors
* Floor
* General condition
* Cracking/movement
* Leakage/dampness
* Deterioration
* Inspection limitations
* Repair/maintenance recommendations

Not every item needs to be mentioned.

**YELLOW – Limited information**

Yellow if a conservatory or porch is referred to and some relevant information is provided, but the notes do not provide enough meaningful inspection information to meet the Green benchmark.

Example Yellow:
“There is a conservatory to the rear.”

**RED – No information**

Red if no meaningful information relating to conservatories or porches can be identified.""",
)

_put(
    "other_joinery_finishes",
    "Other joinery and finishes",
    """**GREEN – Sufficient information**

Green if the notes provide sufficient information regarding the principal external joinery and finishes and provide a meaningful assessment of their visible condition.

Where defects or concerns are identified, the notes should provide sufficient information to understand the nature of the issue and, where relevant, its implication or required action.

Relevant information may include:

* Fascia boards
* Soffits
* External timber joinery
* External decorations
* Paint finishes
* Rot/decay
* Weathering
* Deterioration
* Surface defects
* Maintenance requirements
* Repair or renewal recommendations

Not every item needs to be mentioned.

**YELLOW – Limited information**

Yellow if external joinery or finishes are identified but there is insufficient meaningful information regarding their condition, deterioration or maintenance.

Example Yellow:
“External timber joinery is present.”

**RED – No information**

Red if no meaningful information relating to other joinery and finishes can be identified.""",
)

_put(
    "outside_other",
    "Outside Other",
    """**GREEN – Sufficient information**

Green if the notes provide meaningful information regarding other external matters falling within the outside-property inspection but not otherwise covered by the preceding elements.

Relevant information may include:

* Other significant external features
* Other visible external defects
* External alterations
* Inspection limitations
* Repair/maintenance recommendations
* Other matters specifically recorded under this heading

Not every miscellaneous item needs to be mentioned.

**YELLOW – Limited information**

Yellow if an external matter is mentioned but the notes do not provide sufficient meaningful information to understand its condition, significance or required action.

Example Yellow:
“Other minor external defects were noted.”

**RED – No information**

Red if no meaningful information relating to other external matters can be identified.""",
)

_put(
    "roof_structure",
    "Roof Structure",
    """**GREEN – Sufficient information**

Green if the notes provide sufficient information regarding the accessible roof structure and a meaningful assessment of its visible condition.

Relevant information may include:

* Roof construction/form
* Structural arrangement
* Timber condition
* Structural movement/distortion
* Dampness
* Rot/decay
* Insulation
* Ventilation
* Alterations
* Infestation
* Inspection/access limitations
* Defects or recommendations

Not every item needs to be mentioned. Inspection limitations should be recognised as valid information where parts of the structure cannot be seen.

**YELLOW – Limited information**

Yellow if the roof structure is identified but meaningful information regarding its condition or inspection findings is insufficient.

Example Yellow:
“Traditional timber roof structure.”

**RED – No information**

Red if no meaningful information regarding the roof structure can be identified.""",
)

_put(
    "ceilings",
    "Ceilings",
    """**GREEN – Sufficient information**

Green if the notes provide sufficient information regarding the ceilings and provide a meaningful assessment of their visible condition.

Relevant information may include:

* Ceiling material/finish
* General condition
* Cracking
* Sagging
* Water staining
* Damp-related observations
* Movement
* Damage
* Significant defects
* Repair or overhaul requirements

Not every ceiling or every listed characteristic needs to be mentioned where sufficient representative information has been recorded.

**YELLOW – Limited information**

Yellow if ceiling type or finish is mentioned but there is insufficient meaningful information regarding condition.

Example Yellow:
“Plastered ceilings throughout.”

**RED – No information**

Red if no meaningful ceiling information can be identified.""",
)

_put(
    "walls_partitions",
    "Walls & Partitions",
    """**GREEN – Sufficient information**

Green if the notes provide sufficient information regarding the general nature of the internal walls/partitions and provide a meaningful assessment of their visible condition.

Relevant information may include:

* Construction/type
* Finishes
* Plaster condition
* Dampness
* Cracking
* Movement
* Damage
* Alterations
* Significant defects
* Repair requirements

Not every item needs to be mentioned.

**YELLOW – Limited information**

Yellow if the internal walls are identified or their construction/finish is described but meaningful condition information is insufficient.

Example Yellow:
“Internal walls are plastered.”

**RED – No information**

Red if no meaningful information regarding internal walls and partitions can be identified.""",
)

_put(
    "floors",
    "Floors",
    """**GREEN – Sufficient information**

Green if the notes provide sufficient information regarding the apparent floor construction or type and provide a meaningful assessment of condition or performance.

Relevant information may include:

* Floor construction
* Finishes where relevant
* General condition
* Deflection
* Movement
* Unevenness
* Moisture/dampness
* Ventilation where suspended
* Deterioration
* Significant defects
* Inspection limitations

Not every item needs to be mentioned.

**YELLOW – Limited information**

Yellow if floor construction/type is identified but insufficient meaningful information regarding condition or performance is provided.

Example Yellow:
“Ground floor appears to be of solid construction.”

**RED – No information**

Red if no meaningful floor information can be identified.""",
)

_put(
    "fireplaces_flues",
    "Fireplaces & Flues",
    """**GREEN – Sufficient information**

Green if the notes provide sufficient information to understand the presence, apparent status and relevant visible condition of fireplaces, chimney breasts or flues.

Relevant information may include:

* Present/removed/altered
* Open/sealed
* Apparent use
* Visible condition
* Chimney breast condition
* Flue status where known
* Testing limitations
* Liner where known
* Ventilation
* Dampness
* Alterations or removal
* Further investigation or specialist advice

The AI must not require information about concealed flues, liners or operational safety where these could not reasonably be established during the inspection.

**YELLOW – Limited information**

Yellow if a fireplace, chimney breast or flue is identified but insufficient information is available regarding its status, condition or relevant limitations.

Example Yellow:
“Fireplace present in living room.”

**RED – No information**

Red if no meaningful information regarding fireplaces, chimney breasts or flues can be identified.""",
)

_put(
    "built_in_fittings",
    "Built-in Fittings",
    """**GREEN – Sufficient information**

Green if the notes provide sufficient information regarding the principal built-in fittings and their general visible condition.

Relevant information may include:

* Type of fittings
* Location
* General condition
* Operation where relevant
* Damage/deterioration
* Significant defects

A complete inventory of every built-in fitting is not required.

**YELLOW – Limited information**

Yellow if built-in fittings are merely identified without meaningful information regarding their condition.

Example Yellow:
“Built-in wardrobes to bedroom.”

**RED – No information**

Red if no meaningful information regarding built-in fittings can be identified.""",
)

_put(
    "woodwork_joinery",
    "Woodwork & Joinery",
    """**GREEN – Sufficient information**

Green if the notes provide sufficient information regarding the principal internal woodwork/joinery and provide a meaningful assessment of its general condition.

Relevant information may include:

* Internal doors
* Door frames
* Skirtings
* Architraves
* Staircase
* Handrails/balustrades
* General condition
* Damage/deterioration
* Operation
* Significant defects
* Repair/maintenance requirements

Not every joinery component needs to be separately mentioned.

**YELLOW – Limited information**

Yellow if woodwork/joinery is identified but insufficient meaningful condition information is provided.

Example Yellow:
“Internal doors are timber.”

**RED – No information**

Red if no meaningful information relating to internal woodwork and joinery can be identified.""",
)

_put(
    "bathroom_kitchen_fittings",
    "Bathroom and kitchen fittings",
    """**GREEN – Sufficient information**

Green if the notes provide sufficient information regarding the principal bathroom and kitchen fittings and provide a meaningful assessment of their visible condition or operation.

Relevant information may include:

* Bath
* Basin
* WC
* Shower
* Taps
* Sanitary fittings
* Kitchen units
* Worktops
* Sink
* Visible plumbing
* Sealant
* Visible leaks
* Appliances where relevant
* Operation
* Deterioration
* Significant defects
* Repair or renewal requirements

Not every fitting needs to be individually described where sufficient overall information is available.

**YELLOW – Limited information**

Yellow if bathroom or kitchen fittings are merely identified or listed without sufficient meaningful information regarding their condition, operation or defects.

Example Yellow:
“Bath, basin, WC and fitted kitchen installed.”

**RED – No information**

Red if no meaningful information regarding bathroom and kitchen fittings can be identified.""",
)

_put(
    "inside_other",
    "Inside Other",
    """**GREEN – Sufficient information**

Green if the notes provide sufficient information regarding other internal matters not otherwise covered by the preceding inside-property elements and provide a meaningful assessment where relevant.

Relevant information may include:

* Other significant internal features
* Other visible internal defects
* Internal alterations
* Inspection limitations
* Repair/maintenance recommendations
* Other matters specifically recorded under this heading

Not every miscellaneous item needs to be mentioned.

**YELLOW – Limited information**

Yellow if an internal matter is mentioned but there is insufficient meaningful information to understand its condition, significance or required action.

Example Yellow:
“Other internal defects were noted.”

**RED – No information**

Red if no meaningful information relating to other internal matters can be identified.""",
)

_put(
    "electricity",
    "Electricity",
    """**GREEN – Sufficient information**

Green if the notes provide sufficient information regarding the visible electrical installation and its principal components, together with meaningful observations appropriate to a visual Home Survey inspection.

Relevant information may include:

* Consumer unit
* Apparent age/type
* Visible wiring
* Sockets/switches
* Visible defects
* Damage
* Testing information where known
* Inspection/testing limitations
* Recommendation for electrical testing where appropriate

Green does not require the electrical installation to have been tested.

The absence of visible defects must not be interpreted as confirmation that the electrical installation is safe.

**YELLOW – Limited information**

Yellow if the electrical installation or an individual component is identified but insufficient meaningful information is provided for the section.

Example Yellow:
“Consumer unit located in hallway cupboard.”

**RED – No information**

Red if no meaningful information relating to the electrical installation can be identified.""",
)

_put(
    "gas_oil",
    "Gas / Oil",
    """**GREEN – Sufficient information**

Green if the notes provide sufficient information regarding the apparent gas/oil installation and its principal visible components, together with meaningful observations appropriate to the inspection.

Relevant information may include:

* Fuel type
* Meter
* Visible pipework
* Boiler/appliances
* Storage arrangements where applicable
* Visible condition
* Apparent defects
* Testing limitations
* Specialist advice or testing recommendations

Not every item needs to be mentioned.

**YELLOW – Limited information**

Yellow if the fuel type or an individual component is identified but insufficient meaningful information is provided regarding the installation.

Example Yellow:
“Mains gas is connected.”

**RED – No information**

Red if no meaningful information regarding gas/oil services can be identified.""",
)

_put(
    "water",
    "Water Supply",
    """**GREEN – Sufficient information**

Green if the notes provide sufficient information regarding the apparent water supply or principal visible components and meaningful observations regarding their condition or performance.

Relevant information may include:

* Mains/private supply where known
* Stopcock
* Visible pipework
* Water pressure/flow
* Visible leaks
* Deterioration
* Inspection limitations
* Significant defects
* Further investigation/recommendations

**YELLOW – Limited information**

Yellow if the supply or an individual component is identified but insufficient meaningful information is available regarding condition or performance.

Example Yellow:
“Main stopcock beneath kitchen sink.”

**RED – No information**

Red if no meaningful water supply information can be identified.""",
)

_put(
    "heating",
    "Heating",
    """**GREEN – Sufficient information**

Green if the notes provide sufficient information to understand the general heating arrangement and provide meaningful observations regarding its visible condition, apparent operation or relevant limitations.

Relevant information may include:

* Boiler/heat source
* System type
* Radiators
* Pipework
* Controls
* Apparent operation
* Visible condition
* Defects
* Testing limitations
* Servicing/specialist recommendations

Not every component needs to be mentioned.

**YELLOW – Limited information**

Yellow if the heating system or principal component is identified but insufficient meaningful information is provided regarding condition, operation or inspection limitations.

Example Yellow:
“Gas-fired central heating with radiators.”

**RED – No information**

Red if no meaningful heating information can be identified.""",
)

_put(
    "water_heating",
    "Water Heating",
    """**GREEN – Sufficient information**

Green if the notes provide sufficient information regarding the apparent hot-water arrangement and meaningful observations regarding its condition, operation or relevant limitations.

Relevant information may include:

* Combination boiler
* Cylinder
* Immersion heater
* Other heat source
* Hot-water storage
* Visible condition
* Defects
* Testing limitations
* Specialist advice

**YELLOW – Limited information**

Yellow if the hot-water system/type is identified but insufficient meaningful information regarding its condition or operation is provided.

**RED – No information**

Red if no meaningful water-heating information can be identified.""",
)

_put(
    "drainage",
    "Drainage",
    """**GREEN – Sufficient information**

Green if the notes provide sufficient information regarding the visible or accessible drainage arrangements and provide meaningful observations regarding condition, apparent performance or inspection limitations.

Relevant information may include:

* Drainage type where known
* Inspection chambers
* Rodding points
* Visible pipework
* Apparent flow
* Blockages
* Damage/leakage
* Surface-water drainage
* Inspection limitations
* Further investigation where appropriate

Not every drainage component needs to be visible or inspected.

**YELLOW – Limited information**

Yellow if some drainage information is recorded but insufficient meaningful information is available regarding condition, performance or inspection limitations.

Example Yellow:
“Inspection chamber located in rear garden.”

**RED – No information**

Red if no meaningful drainage information can be identified.""",
)

_put(
    "common_services",
    "Common services",
    """**GREEN – Sufficient information**

Green if the notes identify a common/shared service relevant to the property and provide meaningful information regarding its apparent arrangement, visible condition, operation or relevant inspection limitations.

Relevant information may include:

* Type of common/shared service
* Shared service arrangement
* Visible condition
* Apparent defects
* Testing limitations
* Responsibility where specifically stated
* Further investigation or recommendations

Where no common services are present, an explicit statement confirming this is sufficient information.

Do not require details of a common service that are not available from the inspection.

**YELLOW – Limited information**

Yellow if a common/shared service is mentioned or identified but insufficient meaningful information is provided regarding its arrangement, condition, operation or limitations.

Example Yellow:
“The property has communal heating.”

**RED – No information**

Red if no meaningful information relating to common services can be identified.""",
)

_put(
    "other_services_features",
    "Other services/features",
    """**GREEN – Sufficient information**

Green if the notes provide meaningful information regarding another service or service-related feature not otherwise covered by the main service elements.

Relevant information may include:

* Type of other service/feature
* General arrangement
* Visible condition
* Apparent defect
* Inspection limitation
* Further investigation or recommendation

Not every possible service needs to be mentioned.

The assessment should be based on whether the combined information provides a meaningful inspection picture of the other service or feature actually referred to.

**YELLOW – Limited information**

Yellow if another service or service-related feature is identified but insufficient meaningful information is provided regarding its nature, condition or relevance.

Example Yellow:
“An additional service is present.”

**RED – No information**

Red if no meaningful information regarding other services or features can be identified.""",
)

_put(
    "garage",
    "Garage",
    """**GREEN – Sufficient information**

Green if the notes provide sufficient information regarding the general construction/form of the garage and provide a meaningful assessment of its visible condition.

Relevant information may include:

* Construction
* Roof
* Walls
* Floor
* Doors
* General condition
* Structural defects
* Dampness
* Deterioration
* Repair requirements
* Inspection limitations

Where no garage is present, an explicit statement confirming absence is sufficient.

Not every component needs to be separately described.

**YELLOW – Limited information**

Yellow if the garage is identified or its construction is described but insufficient meaningful condition information is provided.

Example Yellow:
“Detached brick-built garage.”

**RED – No information**

Red if no meaningful garage information can be identified and the notes do not establish whether a garage is present.""",
)

_put(
    "outbuildings",
    "Permanent outbuildings and other structures",
    """**GREEN – Sufficient information**

Green if the notes provide sufficient information regarding significant permanent outbuildings or other structures and provide a meaningful assessment of their visible condition.

Relevant information may include:

* Type/purpose
* Construction
* Roof
* General condition
* Deterioration
* Significant defects
* Repair requirements
* Inspection limitations

Where no permanent outbuildings or other structures are present, an explicit statement confirming absence is sufficient.

Not every component needs to be described.

**YELLOW – Limited information**

Yellow if an outbuilding or structure is identified but insufficient meaningful information is provided regarding its construction, condition or significance.

Example Yellow:
“Timber outbuilding to rear garden.”

**RED – No information**

Red if no meaningful information regarding permanent outbuildings or other structures can be identified.""",
)

_put(
    "grounds_other",
    "Grounds Other",
    """**GREEN – Sufficient information**

Green if the notes provide sufficient information regarding the principal or materially relevant external areas and provide meaningful observations regarding their condition, defects, risks or maintenance requirements.

Relevant information may include:

* Garden
* Paths
* Paving
* Driveway
* Boundary features
* Trees/vegetation
* Retaining walls
* Ground levels
* Drainage
* Other significant external features
* Shared/communal external areas where relevant
* Inspection limitations
* Repair/maintenance recommendations

Not every feature within the grounds needs to be individually described.

**YELLOW – Limited information**

Yellow if one or more external features are identified but insufficient information is available to provide a meaningful overall assessment of the relevant grounds.

Example Yellow:
“Private rear garden.”

**RED – No information**

Red if no meaningful information regarding the grounds can be identified.""",
)

_put(
    "regulation",
    "Regulation",
    """**GREEN – Sufficient information**

Green if the notes identify a regulatory, statutory or approval matter that requires legal-adviser attention and provide enough information to understand the nature of the issue and why further enquiry is required.

Relevant information may include:

* Planning approval
* Building Regulations approval
* Approval for alterations
* Regularisation
* Certificates
* Other statutory approvals
* Other regulatory matters specifically requiring legal investigation

The surveyor does not need to establish the legal position.

**YELLOW – Limited information**

Yellow if a potentially relevant regulatory matter is identified but insufficient information is provided for the legal adviser to understand the issue clearly.

Example Yellow:
“Building Regulations approval should be checked.”

**RED – No information**

Red if no meaningful regulatory matter requiring legal-adviser attention can be identified.""",
)

_put(
    "guarantees",
    "Guarantees",
    """**GREEN – Sufficient information**

Green if the notes identify a relevant guarantee or warranty and provide enough information for the legal adviser to understand what should be checked, retained or transferred.

Relevant information may include:

* Guarantees
* Warranties
* Insurance-backed guarantees
* Guarantees relating to works or installations
* Transferability
* Guarantee documentation
* Expiry/continuation where known

Where the report recommends that guarantee documentation be requested or checked, that is meaningful information.

**YELLOW – Limited information**

Yellow if a guarantee or warranty is mentioned but insufficient information is provided regarding what it covers or what should be checked.

Example Yellow:
“A guarantee may be available.”

**RED – No information**

Red if no meaningful information regarding guarantees or warranties can be identified.""",
)

_put(
    "other_matters",
    "Other matters",
    """**GREEN – Sufficient information**

Green if the notes identify another matter requiring legal-adviser attention and provide sufficient information to understand the matter and the required legal enquiry.

Relevant information may include:

* Lease matters
* Tenure
* Rights of way
* Easements
* Covenants
* Shared maintenance responsibilities
* Party/shared structures
* Neighbouring-owner rights
* Insurance matters
* Service-charge or communal liabilities
* Tenancy/occupancy matters
* Other legal or title matters specifically referred to in the report

The surveyor does not need to determine the legal position.

**YELLOW – Limited information**

Yellow if a potential legal matter is mentioned but the notes do not provide enough information to understand its scope or why it requires legal investigation.

Example Yellow:
“Legal advice should be obtained regarding rights over the chimney.”

**RED – No information**

Red if no meaningful other legal-adviser matter can be identified.""",
)

_put(
    "risks_building",
    "Risks to the building",
    """**GREEN – Sufficient information**

Green if the notes identify a risk affecting the building and provide enough information to understand the nature of the risk, its apparent significance and, where relevant, recommended action.

Relevant information may include:

* Structural movement
* Subsidence/heave
* Dampness
* Water ingress
* Foundation-related risk
* Tree-related structural risk
* Roof or wall risk
* Hidden defect risk
* Material deterioration
* Significant alteration-related risk
* Further investigation or specialist advice

The risk may repeat an issue described elsewhere in the report, provided the notes clearly identify it as a building risk.

**YELLOW – Limited information**

Yellow if a building risk is identified but insufficient information is provided to understand its nature, significance or appropriate next step.

Example Yellow:
“There are concerns regarding movement to the property.”

**RED – No information**

Red if no meaningful information relating to risks to the building can be identified.""",
)

_put(
    "risks_grounds",
    "Risks to the grounds",
    """**GREEN – Sufficient information**

Green if the notes identify a risk affecting the grounds and provide sufficient information to understand the nature or significance of the risk and, where relevant, the appropriate action.

Relevant information may include:

* Flooding
* Surface-water risk
* Tree roots
* Clay/shrinkable ground
* Ground instability
* Ground movement
* Drainage-related ground risk
* Other significant ground risks
* Further investigation or advice

The notes do not need to prove the risk; they should provide a meaningful reported basis for it.

**YELLOW – Limited information**

Yellow if a grounds risk is mentioned but insufficient information is available to understand its significance or required action.

Example Yellow:
“The property is in a flood-risk area.”

**RED – No information**

Red if no meaningful information relating to risks to the grounds can be identified.""",
)

_put(
    "risks_people",
    "Risks to people",
    """**GREEN – Sufficient information**

Green if the notes identify a risk to people and provide enough information to understand the nature of the risk and, where relevant, the recommended action or specialist advice.

Relevant information may include:

* Fire safety
* Smoke alarms
* Gas safety
* Electrical safety
* Unsafe escape arrangements
* Unsafe external or internal features
* Hazardous materials where identified
* Other health and safety concerns
* Specialist testing or remedial recommendations

The notes may recommend specialist testing rather than confirming that a system is safe.

**YELLOW – Limited information**

Yellow if a safety risk is identified but insufficient information is provided to understand the nature, significance or recommended action.

Example Yellow:
“Smoke alarms should be checked.”

**RED – No information**

Red if no meaningful information relating to risks to people can be identified.""",
)

_put(
    "risks_other",
    "Risks Other",
    """**GREEN – Sufficient information**

Green if the notes identify a material risk not otherwise covered by risks to the building, grounds or people and provide sufficient information to understand its significance and, where relevant, any further action.

Relevant information may include:

* Other material risk specifically identified in the report
* Other environmental risk
* Other insurance or ownership-related risk
* Other significant risk not fitting the preceding categories

Not every report will contain an item under this heading.

**YELLOW – Limited information**

Yellow if another risk is mentioned but insufficient information is provided to understand its nature or significance.

Example Yellow:
“Other risks may require further consideration.”

**RED – No information**

Red if no meaningful information relating to other risks can be identified.""",
)

_put(
    "insulation",
    "Insulation",
    """**GREEN – Sufficient information**

Green if the notes provide sufficient information regarding relevant insulation and provide meaningful observations regarding its presence, condition, adequacy or limitations.

Relevant information may include:

* Roof/loft insulation
* Wall insulation where referred to
* Floor insulation where referred to
* Insulation condition
* Missing or inadequate insulation
* Recommendations for improvement

The notes do not need to quantify every area of insulation.

**YELLOW – Limited information**

Yellow if insulation is mentioned or its presence is identified but insufficient meaningful information is available regarding adequacy, condition or limitations.

Example Yellow:
“There is insulation in the roof space.”

**RED – No information**

Red if no meaningful information relating to insulation can be identified.""",
)

_put(
    "energy_heating",
    "Energy Heating",
    """**GREEN – Sufficient information**

Green if the notes provide sufficient information regarding heating in the context of energy efficiency and provide meaningful observations regarding its efficiency, controls or improvement opportunities.

Relevant information may include:

* Heating system
* Boiler/heat source
* Radiators
* Heating controls
* Thermostatic controls
* General efficiency observations
* Energy-efficiency improvements
* Relevant limitations

This section concerns heating from an energy-efficiency perspective. Detailed service condition belongs under Heating in Services.

**YELLOW – Limited information**

Yellow if heating is identified but insufficient meaningful information is provided regarding its energy-efficiency characteristics or limitations.

Example Yellow:
“The property is centrally heated.”

**RED – No information**

Red if no meaningful energy-efficiency information regarding heating can be identified.""",
)

_put(
    "lighting",
    "Lighting",
    """**GREEN – Sufficient information**

Green if the notes provide sufficient information regarding lighting and provide a meaningful observation relevant to energy efficiency.

Relevant information may include:

* Natural lighting
* Adequacy of natural lighting
* Lighting-related energy observations
* Significant lighting limitations
* Recommendations where relevant

Not every light fitting needs to be described.

**YELLOW – Limited information**

Yellow if lighting is mentioned but insufficient meaningful information is provided regarding its relevance to energy efficiency.

Example Yellow:
“Natural light is adequate.”

**RED – No information**

Red if no meaningful information relating to lighting can be identified.""",
)

_put(
    "ventilation",
    "Ventilation",
    """**GREEN – Sufficient information**

Green if the notes provide sufficient information regarding ventilation and provide meaningful observations regarding its adequacy, operation, condensation risk or improvement requirements.

Relevant information may include:

* General ventilation
* Roof-space ventilation
* Bathroom ventilation
* Extractor fans
* Airflow
* Condensation risk
* Inadequate ventilation
* Ventilation-related recommendations

The notes do not need to describe every ventilation opening.

**YELLOW – Limited information**

Yellow if ventilation is mentioned or a ventilation feature is identified but insufficient meaningful information is available regarding adequacy or performance.

Example Yellow:
“Bathroom has an extractor fan.”

**RED – No information**

Red if no meaningful information relating to ventilation can be identified.""",
)

_put(
    "energy_general",
    "General",
    """**GREEN – Sufficient information**

Green if the notes provide sufficient information regarding other energy-efficiency matters not otherwise covered by insulation, heating, lighting or ventilation.

Relevant information may include:

* Feed-in tariffs where applicable
* Green Deal arrangements where applicable
* Other energy-related arrangements specifically referred to in the report
* EPC-related observations
* Other energy-efficiency matters
* Energy-efficiency recommendations

Not every item needs to be mentioned.

**YELLOW – Limited information**

Yellow if an energy-efficiency matter is mentioned but insufficient meaningful information is provided to understand its relevance.

Example Yellow:
“An EPC is available.”

**RED – No information**

Red if no meaningful information relating to other energy-efficiency matters can be identified.""",
)




