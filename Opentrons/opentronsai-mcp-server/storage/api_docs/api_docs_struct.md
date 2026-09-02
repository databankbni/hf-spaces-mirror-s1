# Opentrons API Documentation Structure

This file provides detailed analysis of key files in the Opentrons Python API v2 documentation for LLM context understanding.

Generated on: 2026-07-23 08:56:29 CDT
Knowledge corpus: 9.0.0-k1
Documentation tag: mkdocs-2026-06-02
Default apiLevel: 2.28
About source: claude (claude-sonnet-5)

## Overview

This documentation covers the Opentrons Python API v2, used to write protocols for Opentrons robots (OT-2 and Flex/OT-3). The API allows users to control pipettes, modules, labware, and execute automated laboratory protocols.

Each entry below includes an `<about>` section describing what the file covers. When selecting relevant docs, use the exact relative paths shown below (for example `modules/index.md`).

## File-by-File Analysis

### 1. adapting-ot2-flex.md

<about>
Converting OT-2 protocols to run on Flex, covering required changes to metadata and requirements dictionaries, including apiLevel placement and the mandatory "robotType": "Flex" declaration. Explains updating pipette instrument_name and tip rack load names (e.g., p300_single_gen2 to flex_1channel_1000, opentrons_96_tiprack_300ul to opentrons_flex_96_tiprack_1000ul) via load_instrument and load_labware. Details loading a trash bin with load_trash_bin("A3") to replace the OT-2 fixed_trash, updating deck slot labels from numeric to coordinate format, and converting module load names for Temperature Module, Thermocycler Module, and Heater-Shaker.
</about>

---

### 2. advanced-control/command-line.md

<about>
Running Python protocols directly from the robot's command line using opentrons_execute, without needing the Opentrons App. Covers accessing the command line via Jupyter Notebook's New > Terminal option or through SSH, copying protocol files to the robot with scp, and executing them. Explains default behavior, including printing the run log (matching what's shown in the Opentrons App) and internal logs at warning level or above, plus how to customize these outputs using opentrons_execute --help for additional command options.
</about>

---

### 3. advanced-control/index.md

<about>
Advanced control options for operating an Opentrons robot outside standard protocol execution through the app, covering direct interaction with robot hardware and components like the gantry arm. This index links to guidance on using Jupyter notebook for interactive protocol development and testing, command line access for direct robot control, and robot motor control for low-level manipulation of movement systems.
</about>

---

### 4. advanced-control/jupyter.md

<about>
Jupyter Notebook access and usage on Flex and OT-2 robots via port 48888, covering opentrons.execute.get_protocol_api() for interactive cell-based protocol development, the required home() call before other commands, and running previously written protocols by defining and invoking a run() function. Explains setting labware offsets manually using set_offset() since Labware Position Check must be run separately through the Opentrons App, including differences in offset reuse behavior between Flex and OT-2 across deck locations, tip racks, and move_labware().
</about>

---

### 5. advanced-control/robot-motors.md

<about>
Robot motor control on Flex covers low-level RobotContext methods for direct axis movement, bypassing standard pipette and gripper abstractions. Includes move_to, move_axes_to, and move_axes_relative for controlling gantry (X, Y), mount Z-axes (Z_L, Z_R), gripper (Z_G, G), plunger axes (P_L, P_R), and the 96-channel pipette tip pickup motor (Q). Also covers open_gripper_jaw and close_gripper_jaw, plus helper methods axis_coordinates_for, plunger_coordinates_for_volume, and plunger_coordinates_for_named_position for generating axis coordinate maps.
</about>

---

### 6. building-block-commands/index.md

<about>
Python API building block commands form the basic robot actions used to construct more complex protocol steps. This overview page links to three subsections: pipette tip manipulation covering pick-up, drop, and return of tips; liquid control covering aspirating, dispensing, blow out, touch tip, mixing, and air gap procedures; and utility commands for pausing or delaying protocols, checking the robot's door, and controlling robot lights. These building blocks underlie the complex commands that combine multiple actions into fewer lines of protocol code.
</about>

---

### 7. building-block-commands/liquids.md

<about>
Liquid handling with InstrumentContext.aspirate() and dispense() methods, covering volume, well location, and flow rate parameters for Flex and OT-2 pipettes. Explains location and end_location parameters accepting Well or Location objects, using Well.top(), Well.bottom(), and Well.meniscus() for positioning, plus well_bottom_clearance defaults. Details meniscus-relative pipetting via measure_liquid_height() or Labware.load_liquid(), movement_delay for multi-location moves, and rate versus absolute flow_rate settings (mutually exclusive).
</about>

---

### 8. building-block-commands/pipette-tips.md

<about>
Pipette tip handling in the Opentrons Python API, covering pick_up_tip(), drop_tip(), and return_tip() methods. Explains automatic tip tracking across single or multiple tip racks, using for loops with range for automated tip pickup across 96 or more tips, and associating tip racks via load_instrument()'s tip_racks argument. Details specifying custom drop locations including trash bins and waste chutes, the alternate_drop_location argument (new in API version 2.28) for varying drop positions, partial tip pickup support for return_tip() (2.28), and how used tips are tracked differently since API version 2.2, applicable to both Flex and OT-2 robots.
</about>

---

### 9. building-block-commands/utilities.md

<about>
Utility commands for Opentrons Flex and OT-2 protocols, covering ProtocolContext.delay() and pause() for timed or manual stops, home() and InstrumentContext.home()/home_plunger() for gantry and pipette homing, comment() for displaying messages in the Opentrons App, and capture_image() for taking deck photos with the built-in camera (with options like home_before and custom filenames). Also documents set_rail_lights() and rail_lights_on for controlling and checking rail lights, and door_closed for checking the OT-2 door safety switch status, introduced in robot software version 3.19.
</about>

---

### 10. complex-commands/index.md

<about>
Complex commands in the Opentrons Python API combine building block commands into single method calls on InstrumentContext, handling multiple wells and tip usage automatically. Legacy commands include transfer(), distribute(), and consolidate(), which support optional behaviors like air gaps, droplet knocks, mixing, and blow-out. Liquid class commands—transfer_with_liquid_class(), distribute_with_liquid_class(), and consolidate_with_liquid_class()—use liquid class definitions to adjust transfer behavior based on liquid properties such as viscosity. Related pages cover source/destination well selection, order of operations, and additional parameters affecting complex command behavior.
</about>

---

### 11. complex-commands/order-operations.md

<about>
Order of operations for Opentrons complex commands, covering transfer(), distribute(), and consolidate() versus liquid class methods like transfer_with_liquid_class() and distribute_with_liquid_class(). Details the fixed sequence of steps including tip pickup, mixing, aspirating, touch tip, air gap, dispensing, blow out, and tip drop, plus liquid class-specific steps like submerging, pre-wetting, and delays. Explains tip refilling behavior when volumes exceed pipette capacity, disposal volume effects on distribute(), and using lists of volumes with source/dest arguments to skip wells, including behavior with new_tip parameter set to "never" or "always".
</about>

---

### 12. complex-commands/parameters.md

<about>
Complex command parameters for Opentrons Python API methods like transfer(), distribute(), consolidate(), and transfer_with_liquid_class() are covered, including new_tip (once, always, never, per source, per destination) for tip pickup behavior, mix_before and mix_after for mixing with repetition/volume tuples, disposal_volume for extra aspirated liquid in distribute(), touch_tip for post-aspirate/dispense touches, and air_gap for preventing liquid seepage. Discusses tip refilling strategies, cross-contamination avoidance, and how liquid class definitions govern these behaviors in liquid-class-aware commands, referencing InstrumentContext methods and well_bottom_clearance.
</about>

---

### 13. complex-commands/sources-destinations.md

<about>
Source and destination well handling for complex liquid handling commands in the Opentrons Python API, covering transfer(), transfer_with_liquid_class(), distribute(), distribute_with_liquid_class(), consolidate(), and consolidate_with_liquid_class(). Explains restrictions on well counts for each method, how single wells versus lists are accepted, and the aspirate/dispense ordering patterns each command follows. Details many-to-many transfer mapping, well list "stretching" for uneven source/destination sizes, divisibility requirements, well ordering pitfalls with rows() and columns(), and tip handling behavior including new_tip and keep_last_tip parameters for liquid class commands.
</about>

---

### 14. deck-slots.md

<about>
Deck slot addressing for Flex and OT-2 robots, covering physical labeling systems (Flex coordinates A1–D4, OT-2 numeric 1–11), and how the API accepts both coordinate and numeric slot formats interchangeably since API version 2.15. Explains deck configuration for Flex robot system 7.1.0+, including staging area slots (column 4), trash bin fixtures via load_trash_bin(), and waste chute setup via load_waste_chute() introduced in API 2.16. Covers load_labware(), move_labware(), module placement conflicts, gripper compatibility, and deck conflict checks preventing protocol runs until resolved.
</about>

---

### 15. examples.md

<about>
Python API protocol examples for Opentrons Flex and OT-2 robots, illustrating full working protocols using apiLevel 2.28. Covers loading labware (tip racks, well plates, reservoirs, trash bins) and pipettes (flex_1channel_1000, p300_single_gen2), plus liquid transfer techniques ranging from basic building-block commands like pick_up_tip(), aspirate(), and dispense() to advanced methods such as transfer() and transfer_with_liquid_class(), including Opentrons-verified liquid class definitions restricted to Flex pipette/tip combinations.
</about>

---

### 16. index.md

<about>
Opentrons Python Protocol API landing page introducing how the API works, with side-by-side Flex and OT-2 example protocols demonstrating metadata, requirements (robotType and apiLevel, shown as 2.28), loading labware like corning_96_wellplate_360ul_flat and tip racks, loading pipettes (flex_1channel_1000 or p300_single) via load_instrument, and basic commands such as pick_up_tip, aspirate, dispense, and drop_tip. It points to further resources including the tutorial, examples, Building Block Commands, Complex Commands, and Modules pages, plus links to the Opentrons App, support contacts, custom protocol development services, and contribution guidelines for the open-source project.
</about>

---

### 17. labware.md

<about>
Labware handling in the Opentrons Python API, covering default labware from the Labware Library versus custom labware created via the Labware Creator. Explains loading labware and lids with load_labware(), load_lid_stack(), and Labware.load_lid_stack() for Flex and OT-2, plus loading labware on adapters using load_adapter() (v2.15) and the adapter parameter, including deprecated combination definitions. Details well-access methods—wells(), rows(), columns(), wells_by_name(), rows_by_name(), columns_by_name()—dictionary and list indexing, and iterating well groups. Also covers labeling liquids with define_liquid() and Labware.load_liquid() for tracking well contents and volumes.
</about>

---

### 18. liquid-class-definitions.md

<about>
Opentrons-verified liquid class definitions for the Python API, covering three predefined categories used to configure pipette transfer behavior for different fluid types: Aqueous (based on deionized water), Viscous (based on 50% glycerol), and Volatile (based on 80% ethanol). Each section references detailed parameter tables specifying the liquid class properties applied during pipetting operations. These built-in liquid classes help automate aspiration and dispense settings tailored to fluid characteristics, supporting accurate liquid handling without manual configuration of flow rates, delays, or other transfer parameters for common liquid behaviors encountered in lab protocols.
</about>

---

### 19. liquid-class-tables/aqueous.md

<about>
Aqueous liquid class aspirate parameters for Opentrons Flex pipettes across multiple pipette and tip configurations, including 1-channel and 8-channel 50 µL and 1000 µL pipettes, plus 96-channel 200 µL and 1000 µL pipettes. Tables detail behavior by volume for submerge speed, aspirate flow rate, delay after aspirating, retract speed, delay after retracting, and air gap, with values varying by tip volume (20 µL, 50 µL, 200 µL, 1000 µL) and target aspiration volume. Useful for configuring liquid class transfer functions and fine-tuning aspiration behavior in protocol scripting for aqueous liquids.
</about>

---

### 20. liquid-class-tables/viscous.md

<about>
Aspirate settings for viscous liquid classes across pipette and tip volume combinations, including 1-channel and 8-channel pipettes with 50 µL and 1000 µL tips, plus the 96-channel pipette with 200 µL tips. Tables detail submerge speed, aspirate flow rate by volume, volume correction (µL adjustment) by aspirate volume, delay after aspirating, retract speed, delay after retracting, and air gap by volume, with values broken out per tip size (20 µL, 50 µL, 200 µL, 1000 µL) to fine-tune aspiration behavior for viscous liquid handling.
</about>

---

### 21. liquid-class-tables/volatile.md

<about>
Aspirate behavior settings for the volatile liquid class, detailing default parameters used by Opentrons pipettes when drawing up liquid. Covers submerge speed, aspirate flow rate by volume, correction by volume, delay after aspirating, retract speed, delay after retracting, and air gap by volume, each broken down across pipette configurations including 1-channel and 8-channel pipettes at 50 µL and 1000 µL volumes, plus the 96-channel pipette at 200 µL. Values are organized in tables by specific liquid volumes (e.g., 1 µL, 20 µL, 50 µL, 200 µL, 1000 µL) to show how flow rates, corrections, and air gaps scale with aspirated volume for accurate volatile liquid handling.
</about>

---

### 22. liquid-classes.md

<about>
Liquid classes for Flex protocols, covering Opentrons-verified definitions (Aqueous/water, Volatile/ethanol_80, Viscous/glycerol_50) and their properties like submerge speed, flow rate, touch tip, air gap, push out, blow out, and delay. Explains using ProtocolContext.get_liquid_class() to select a class and InstrumentContext.transfer_with_liquid_class() (introduced in API version 2.24) to perform transfers with pipette, tiprack, trash, and labware setup. Also covers customizing liquid class properties via get_for(), with an optional version parameter (added in 2.26) to select prior definition versions.
</about>

---

### 23. modules/absorbance-plate-reader.md

<about>
Absorbance Plate Reader module (absorbanceReaderV1) usage on Flex, loadable only in slots A3–D3. Covers lid control via open_lid(), close_lid(), and is_lid_on(), including gripper-based movement and required lid closure before initialization. Details AbsorbanceReaderContext.initialize() for setting single or multi-wavelength modes (450, 562, 600, 650 nm), optional reference wavelength, and read() for capturing plate data, with optional CSV export via export_filename. Explains interpreting returned nested dictionary data (optical density values by wavelength and well) versus structured CSV output, and reusing exported CSVs as runtime parameters with detect_dialect=False.
</about>

---

### 24. modules/concurrent.md

<about>
Concurrent module actions for Heater-Shaker, Temperature, and Thermocycler Modules, covering commands like set_target_temperature(), set_shake_speed(), start_set_temperature(), start_set_lid_temperature(), start_set_block_temperature(), and start_execute_profile(), which return Task objects running in the background while the robot continues protocol steps. Explains how to synchronize timing using wait_for_tasks() and create_timer() to pause execution until a module reaches target temperature or an incubation period completes, including guidance on avoiding errors when waiting for multiple tasks on the same module, such as sequential temperature changes on a Temperature Module.
</about>

---

### 25. modules/flex-stacker.md

<about>
Flex Stacker Module setup on Opentrons Flex, covering loading up to four stackers in column 4 deck slots (A4, C4), deck slot conflicts with column 3 fixtures, and configuring stored labware with set_stored_labware() and set_stored_labware_items(), including capacity for tip racks, PCR plates, and deep well plates. Details methods like get_max_storable_labware(), get_current_storable_labware(), get_stored_labware(), retrieve(), store(), fill(), and empty() for managing labware stacks, plus using move_labware() with the Flex Gripper to transfer labware between the Stacker and deck. Introduced in API version 2.25.
</about>

---

### 26. modules/heater-shaker.md

<about>
Heater-Shaker module usage in the Python API, covering deck slot placement rules for Flex and OT-2, including restrictions on adjacent modules, tall labware, and 8-channel pipettes on OT-2. Details labware latch control via open_labware_latch() and close_labware_latch(), loading adapters and labware with load_adapter() and load_labware(), standalone adapter types, and pre-configured adapter-labware combinations.
</about>

---

### 27. modules/index.md

<about>
Overview of hardware modules for Flex and OT-2 robots, covering deck-mounted peripherals like the Absorbance Plate Reader Module, Flex Stacker Module, Heater-Shaker Module, Magnetic Block, Magnetic Module, Temperature Module, and Thermocycler Module. Explains the difference between powered modules (USB-connected, auto-detected) and unpowered modules like the Magnetic Block. Links to related topics including module and labware setup, concurrent module actions during pipetting or gripper steps, and loading multiple modules of the same type. Notes that OT-2 users on API version 2.14 or earlier must use numeric deck slots instead of coordinate slots.
</about>

---

### 28. modules/magnetic-block.md

<about>
Magnetic Block module usage in the Opentrons Python API, covering loading the module with load_module using module_name "magneticBlockV1" into a deck slot, and adding labware such as a 96-well plate via load_module and load_labware. Demonstrates moving labware between deck locations using the gripper with protocol.move_labware and the use_gripper parameter, relevant to Flex robots supporting gripper-based labware transfers. Introduced in API version 2.15, this reference helps with questions about magnetic modules, labware placement, deck slots, and gripper-enabled automated labware movement commands.
</about>

---

### 29. modules/magnetic-module.md

<about>
Magnetic Module control in the Opentrons Python API, covering loading compatible labware (Bio-Rad, NEST, Thermo Scientific Nunc, USA Scientific PCR and deep well plates) via load_labware() and checking magdeck_engage_height. Details engage() and disengage() methods, including height_from_base and offset parameters for positioning magnets relative to labware base, introduced in API version 2.0 and 2.2 respectively. Also covers the status property for checking engaged/disengaged state, deactivate() for turning off the module, and differences between GEN1 and GEN2 Magnetic Module hardware, including recommended bead attraction times and Adapter Magnets for added strength.
</about>

---

### 30. modules/multiple-same-type.md

<about>
Loading multiple instances of the same module type on Flex and OT-2 robots using protocol.load_module() with module_name or load_name parameters. Explains how module load order is determined by USB port connection rather than deck slot position—modules connected to lower-numbered USB ports load first regardless of their assigned deck slot location. Includes example code for temperature module gen2 on both robot types, showing deck slot placement (D1/C1 for Flex, slots 1/3 for OT-2) alongside corresponding USB port assignments (ports 2/6 for Flex, ports 1/2 for OT-2), with diagrams illustrating physical USB connection order.
</about>

---

### 31. modules/setup.md

<about>
Module setup in the Opentrons Python API covers loading modules onto the deck with ProtocolContext.load_module(), including Temperature Module GEN1/GEN2, Magnetic Module GEN1/GEN2, Thermocycler Module GEN1/GEN2, Heater-Shaker Module GEN1, Magnetic Block GEN1, Absorbance Plate Reader Module, and Flex Stacker Module, along with their API load names and minimum required API versions. It also explains loading labware onto a module using the module context's load_labware() method, module and labware compatibility considerations, and additional labware parameters like label, version, and namespace, applicable to both Flex and OT-2 robot types.
</about>

---

### 32. modules/temperature-module.md

<about>
Temperature Module Python API covers loading labware and adapters via load_adapter() and load_labware(), including standalone adapter definitions (aluminum flat bottom plate, 96-well aluminum block, 96 deep well temp mod adapter), 24-well block-and-tube combinations, and 96-well block-and-plate combinations for backwards compatibility. It details temperature control using blocking set_temperature() (since API 2.0) versus concurrent start_set_temperature() (since API 2.27), the deactivate() method, and checking module state with the status property ("holding at target" or "idle").
</about>

---

### 33. modules/thermocycler.md

<about>
Thermocycler module control via the Python API, covering lid operations (open_lid, close_lid, set_lid_temperature, start_set_lid_temperature, deactivate_lid) and block temperature control (set_block_temperature, start_set_block_temperature, deactivate_block), including hold times, ramp_rate, and block_max_volume parameters. Also details Thermocycler profiles as lists of temperature/hold_time dictionaries executed via execute_profile or start_execute_profile with repetitions, plus concurrent module action support introduced in version 2.27. Ramp rate control was added in version 2.28.
</about>

---

### 34. moving-labware.md

<about>
Moving labware with the Opentrons Flex covers ProtocolContext.move_labware() and move_lid() for relocating labware, tip racks, and lids between deck slots, modules, adapters, the waste chute, and off-deck locations using OFF_DECK. Explains automatic gripper-based moves (use_gripper=True) versus manual pauses requiring user confirmation, supported labware like NEST plates, Armadillo and Opentrons PCR plates, Flex tip racks, and Opentrons lids. Details module accessibility requirements (open_labware_latch, open_lid) for Heater-Shaker and Thermocycler, load_lid_stack usage, and reloading tip racks mid-protocol.
</about>

---

### 35. pipettes/characteristics.md

<about>
Pipette characteristics for Opentrons Flex and OT-2, covering multi-channel movement with 1-, 8-, and 96-channel pipettes across 96-well and 384-well plates, including primary channel behavior, configure_nozzle_layout(), partial tip pickup, and well-access patterns for aspirate/dispense with InstrumentContext. Also details flow rate control via InstrumentContext.flow_rate.aspirate, .dispense, and .blow_out, configure_for_volume() resetting defaults, and the deprecated InstrumentContext.speed (API 2.13 and earlier).
</about>

---

### 36. pipettes/index.md

<about>
Pipettes covers the Opentrons Python API's treatment of Flex and OT-2 pipettes, the configurable devices used to move liquids during protocol execution. It serves as an index to related pages: loading pipettes into a protocol, pipette characteristics like movement speed and deck positioning, partial tip pickup configurations for multi-channel pipettes (which can be combined with full tip pickup in one protocol), and volume modes for Flex 50 µL pipettes, which require low-volume mode for accurate dispensing of very small liquid amounts. Liquid handling details are covered separately in Building Block Commands and Complex Commands documentation.
</about>

---

### 37. pipettes/loading.md

<about>
Loading pipettes with load_instrument() covers API load names for Flex pipettes (flex_1channel_50/1000, flex_8channel_50/1000, flex_96channel_200/1000) and OT-2 pipettes (P20, P300, P1000 GEN2 models), plus GEN1 references. Includes code samples for mounting single, multi-, and 96-channel pipettes, using tip_racks for automatic tip tracking, and manual pick_up_tip location specification. Details tip-pipette compatibility tables matching pipette capacity to compatible Flex tip racks (20µL added in version 2.28), and configuring trash_container using trash bins or waste chutes, including TrashBin/WasteChute support added in version 2.16.
</about>

---

### 38. pipettes/partial-tip-pickup.md

<about>
Partial tip pickup on Flex robots using configure_nozzle_layout() with InstrumentContext, covering nozzle layout constants COLUMN, ROW, SINGLE, ALL, and PARTIAL_COLUMN imported from opentrons.protocol_api. Explains configuring the 96-channel pipette for column, row, and single-tip pickup, and the 8-channel pipette for single and partial column (2-7 tip) pickup, including start and end nozzle parameters, tip_racks assignment, pick_up_tip() and drop_tip() usage, manual tip tracking with Labware.rows() and rows_by_name(), and version notes (2.16, 2.20) for each layout style.
</about>

---

### 39. pipettes/volume-modes.md

<about>
Volume modes for Flex 1-Channel 50 µL and 8-Channel 50 µL pipettes, which must switch into low-volume mode to accurately handle very small liquid amounts. Explains InstrumentContext.configure_for_volume(), introduced in API version 2.15, which sets minimum/maximum volume ranges (1–4.9 µL and 5–50 µL) and default push-out volumes (7 µL or 2 µL), linking to push-out-after-dispense documentation. Covers required pipette state (no liquid present when calling configure_for_volume), tip pick-up order, and best practices for calling it once per transfer/aspirate or within a for loop when handling variable volume lists.
</about>

---

### 40. reference/absorbance-plate-reader.md

<about>
Absorbance Plate Reader API reference covering the AbsorbanceReaderContext class, used for controlling Opentrons absorbance reader modules within a protocol. This documentation details the public methods and inherited members available on AbsorbanceReaderContext for initializing measurements, reading absorbance values, and managing plate reader operations. It excludes internal implementation details like broker, geometry, load_labware_object, and load_adapter methods, focusing instead on the user-facing API surface relevant to configuring and executing absorbance readings as part of automated liquid handling workflows involving compatible labware and plate-based assays.
</about>

---

### 41. reference/execute-simulate.md

<about>
Python API reference for the opentrons.execute and opentrons.simulate modules, which allow protocol authors to run or simulate Opentrons Python API protocols outside the normal robot execution environment. These modules are useful for testing protocol logic, checking for errors, and running protocols directly from the command line or a script on a computer or robot, without needing the full Opentrons App. Relevant for questions about protocol validation, dry runs, simulation results, and programmatic execution of pipette, labware, and module commands during development.
</about>

---

### 42. reference/flex-stacker.md

<about>
Flex Stacker module API reference covering the FlexStackerContext class, which provides Python methods for controlling the Flex Stacker labware storage and retrieval hardware module on Flex robots. This reference documents the inherited members and methods available for programmatically managing stacker operations within Opentrons protocols, including loading, storing, and retrieving labware stacks. Relevant for questions about Flex Stacker module commands, labware handling automation, hardware module integration, and API methods specific to this storage module's context object in the Protocol API.
</about>

---

### 43. reference/heater-shaker.md

<about>
Heater-Shaker module control via the HeaterShakerContext class in the Opentrons Python Protocol API. Covers methods and properties for managing the heater-shaker hardware module, including setting and reading target temperature, controlling shaking speed, latching and unlatching the labware clamp, and monitoring module status during protocol execution. Useful for questions about integrating heater-shaker modules into protocols, temperature and shake control commands, labware latch operations, and module state inheritance within the broader protocol API context for Flex and OT-2 robots.
</about>

---

### 44. reference/instruments.md

<about>
Python API reference for the InstrumentContext class, covering pipette instrument methods and properties available in the Opentrons Python Protocol API. This page documents the attributes and functions used to control pipette behavior during protocol execution, such as aspirating, dispensing, mixing, transferring liquids, tip handling, and other pipette-related actions. It serves as a reference for developers configuring pipette instruments on Flex or OT-2 robots, excluding delay-related and internal/private methods from the listing.
</about>

---

### 45. reference/labware.md

<about>
Python API reference for the Labware class and fixed trash disposal locations in Opentrons protocols. Covers Labware object properties and methods used to reference wells, tip racks, and reservoirs on the deck, excluding internal tip-tracking methods like next_tip, use_tips, previous_tip, and return_tips. Also documents TrashBin and WasteChute classes, including their top attribute, which represent Flex-compatible trash and waste chute fixtures used for discarding tips and liquid waste during protocol execution.
</about>

---

### 46. reference/magnetic-block.md

<about>
Python API Reference for MagneticBlockContext, the class representing a Magnetic Block module on Flex robots. This page documents the inherited members and API methods available for interacting with the Magnetic Block, which is used to hold labware in place using magnetic force during protocol execution, such as for bead-based sample separations. It covers the object model used to reference and control this module within Opentrons Python Protocol API scripts, relevant to protocols involving magnetic labware handling on compatible robot types.
</about>

---

### 47. reference/magnetic-module.md

<about>
Python API reference for the MagneticModuleContext class, covering methods and properties used to control the Magnetic Module in Opentrons protocols. This includes engaging and disengaging the module's magnets, setting engagement height, and managing labware placed on the module. The reference documents public members inherited by the class, excluding internal implementation details like broker, geometry, load_labware_object, and calibrate. Useful for questions about magnetic bead-based workflows, module control commands, and pipette interactions with labware positioned on the Magnetic Module during protocol execution on supported Opentrons robots.
</about>

---

### 48. reference/protocols.md

<about>
Python API reference for the ProtocolContext class, the central object representing a protocol run in Opentrons Python API v2. Covers its methods and properties for controlling protocol execution, excluding internal items like location_cache, cleanup, clear_commands, group_steps, and create_and_start_step_group. Also documents the Task class. Relevant for questions about structuring protocols, managing steps, pipette and labware interactions within a protocol, and general protocol-level API methods used across Flex and OT-2 robots.
</about>

---

### 49. reference/robot-motors.md

<about>
Robot motors reference covering the RobotContext class within the Opentrons Python Protocol API. This documentation addresses low-level robot motor control and hardware axis management, relevant for advanced protocol authors working directly with robot movement mechanics on Flex or OT-2 systems. It serves as an API reference entry point for developers needing to interact with or query robot motor states beyond standard pipette and labware commands, supporting more granular control over robot hardware behavior within custom protocol logic.
</about>

---

### 50. reference/temperature-module.md

<about>
Python API reference for TemperatureModuleContext, covering methods and properties available for controlling the Temperature Module within Opentrons protocols. This class provides the interface for setting and managing temperature on the module, including functionality for reaching and maintaining target temperatures. Relevant for protocols that require temperature-controlled labware, such as sample cooling or heating steps, and is applicable to both Flex and OT-2 robot types using the Python Protocol API.
</about>

---

### 51. reference/thermocycler.md

<about>
Thermocycler module API reference, covering the ThermocyclerContext class used to control the Thermocycler Module in Opentrons protocols. It documents public methods and properties for managing lid position (open/close), block and lid temperature control, running profiles for PCR-style temperature cycling, and monitoring module state. Internal attributes like broker, geometry, load_labware_object, load_adapter, hold_time, ramp_rate, and cycle/step counters are excluded from the listing. This reference is relevant for protocols using the Thermocycler on Flex or OT-2 robots to automate heating, cooling, and thermal cycling steps for applications such as PCR amplification.
</about>

---

### 52. reference/types.md

<about>
Reference for core Opentrons Python API types used throughout protocol scripting. Covers Location, Point, Mount, and StringAxisMap from opentrons.types for representing coordinates, deck positions, and pipette mount assignments; APIVersion for specifying protocol API compatibility; CSVParameter for runtime CSV file parameters; and OFF_DECK along with OffDeckType for marking labware as removed from the deck. These types support labware placement, pipette movement, robot configuration, and runtime parameter handling in Opentrons Flex and OT-2 protocols.
</about>

---

### 53. reference/wells-liquids.md

<about>
Python API reference for wells and liquids, covering the Well class with its properties and methods for accessing well geometry, position, and location data within labware, excluding internal and liquid-height estimation helpers. Also documents the Liquid class for defining and tracking liquids loaded into a protocol, and the LiquidClass class, focusing on its get_for method used to retrieve predefined liquid class transfer properties for specific pipette and tip combinations, supporting accurate aspirate and dispense behavior configuration.
</about>

---

### 54. robot-position.md

<about>
Labware and deck positioning in the Opentrons Python API, covering well positions via Well.top(), Well.bottom(), Well.center(), and Well.meniscus() methods, plus default aspirate/dispense clearance using well_bottom_clearance. Explains Labware Position Check for offset calculation, movement relative to TrashBin and WasteChute objects using top() methods, deck coordinate system (Location and Point objects), and independent pipette movement with move_to(). References InstrumentContext.aspirate(), dispense(), transfer(), and measure_liquid_height(), noting Flex-only liquid height detection and differences between OT-2 and Flex collision handling at well bottoms.
</about>

---

### 55. runtime-parameters/choosing.md

<about>
Guidance on designing effective runtime parameters for Opentrons protocols, focusing on decision-making rather than API syntax. Covers how to align parameters with the protocol's core scientific task (e.g., sample count vs. reagent kit choice), avoid contradictory or dangerous configurations (such as ambiguous pipette mount assignments), and set sensible minimum and maximum boundaries for numerical parameters like dilution counts, dilution factors, and row numbers. Uses the serial dilution tutorial protocol as a recurring example to illustrate combining parameters and enforcing logical limits based on labware format, such as 96-well versus 384-well plates.
</about>

---

### 56. runtime-parameters/defining.md

<about>
Runtime parameter definitions using the required add_parameters() function, which takes a ParameterContext argument and must precede run(). Covers the four built-in parameter types—boolean (add_bool), integer (add_int), float (add_float), and string (add_str)—along with configuration options like variable_name, display_name, description, default, minimum, maximum, unit, and choices for menu-based selection. Also explains CSV file parameters (add_csv_file), introduced in API version 2.20, which lack default values and are limited to one per protocol, while other parameter types were introduced in version 2.18.
</about>

---

### 57. runtime-parameters/index.md

<about>
Runtime parameters overview covering how to add user-customizable variables to Python protocols, letting technicians adjust behavior at setup without editing code. It links to guidance on choosing good parameters, defining boolean, numeric, and string parameter types, and using parameter values to drive protocol logic and API calls. It also introduces practical use cases like setting sample count, enabling a dry run toggle, and cherrypicking with CSV-specified locations and volumes, plus style and usage advice for writing clear parameter names and descriptions for the people running the protocol.
</about>

---

### 58. runtime-parameters/style.md

<about>
Style conventions for naming and describing runtime parameters in the Opentrons Python API. Covers writing parameter names as concise nouns, crafting action-oriented descriptions with proper punctuation, and using sentence case. Addresses formatting numbers, ordering choices logically (numeric ascending/descending or alphabetical), and type-specific guidance for Booleans (On/Off values, avoiding double negatives), number choices (using minimum/maximum ranges versus explicit choices, adding units to display names), and strings (avoiding yes/no synonyms in favor of Boolean toggles). Useful for designing display_name, description, and choices attributes for protocol parameters.
</about>

---

### 59. runtime-parameters/use-case-cherrypicking.md

<about>
Cherrypicking protocol design using CSV runtime parameters on Flex robots, demonstrating add_csv_file() and parse_as_csv() to dynamically load labware and drive liquid transfers. Covers building a parameter with add_parameters(), parsing CSV rows into source slot, source well, and volume data, deduplicating slots for loading Opentrons Tough PCR plates, and referencing labware via ProtocolContext.deck. Also details load_labware(), load_instrument() for the flex_1channel_1000 pipette, load_trash_bin(), Labware.wells(), and using pipette.transfer() in a loop with enumerate() to map source and destination wells based on CSV data, at apiLevel 2.28.
</about>

---

### 60. runtime-parameters/use-case-dry-run.md

<about>
Runtime parameters for implementing a dry run toggle in Opentrons Python protocols, using a Boolean parameter (add_bool) accessed via protocol.params.dry_run. Covers conditionally skipping delays with protocol.delay() and Thermocycler Module operations (set_block_temperature, set_lid_temperature, execute_profile), shortening mix() repetitions, and managing tip handling by choosing between drop_tip() and return_tip(). Also addresses replenishing tip racks differently for dry versus live runs using reset_tipracks() and move_labware() with the gripper or manual placement, plus writing clear parameter descriptions.
</about>

---

### 61. runtime-parameters/use-case-sample-count.md

<about>
Runtime parameters for sample count in Flex protocols, showing how an integer parameter with defined choices (8, 16, 24, 32) drives dynamic protocol behavior. Covers calculating column counts from sample count for 8-channel pipettes, computing required tip rack quantities using math.ceil(), and conditionally loading labware via load_labware() based on slot lists. Demonstrates load_liquid() for reagents and samples with volume calculations scaled by column_count, iterating over wells and labware with list slicing and zip(), and using move_labware() to relocate staging area tip racks when pipettes cannot reach them directly, referencing Flex pipettes like flex_8channel_50 and flex_1channel_100...
</about>

---

### 62. runtime-parameters/using-values.md

<about>
Runtime parameter values in Opentrons Python protocols, accessed through ProtocolContext.params, with each attribute named after a parameter's variable_name (e.g., params.dry_run, params.sample_count, params.volume). Covers parameter types, casting integers to strings, integer vs float division pitfalls, and handling CSV parameters via the CSVParameter class using .file, .contents, or parse_as_csv() (new in API version 2.20), including RuntimeParameterRequiredError for analysis-time defaults.
</about>

---

### 63. tutorial.md

<about>
Serial dilution walkthrough for building a complete Opentrons Python protocol from scratch, covering both Flex and OT-2 robots. Explains the protocol file structure including the import statement, metadata dictionary (apiLevel, protocolName, description, author), and the requirements block specifying robotType and apiLevel, using API version 2.16 as an example. Details the run() function with ProtocolContext argument, loading labware (tip racks, reservoirs, well plates) via load_labware(), configuring trash bins with load_trash_bin() on Flex versus the fixed OT-2 trash, and loading pipettes like flex_1channel_1000 or p300_single_gen2 with load_instrument(), including tip rack assignment and...
</about>

---

### 64. versioning.md

<about>
Python Protocol API versioning explains how major and minor version numbers govern protocol behavior, how to declare apiLevel in metadata or requirements, and maximum supported ranges per robot type—Flex supports 2.15–2.28, OT-2 supports 2.0–2.28, with robot software 9.0.0 as the latest. It includes a full API-to-robot-software correspondence table and a changelog detailing feature additions by version, such as liquid classes, Heater-Shaker support, Flex Stacker Module, concurrent module commands, camera capture, partial tip pickup, meniscus location, robot motor control methods, and pipette/labware/module-related API changes across versions.
</about>

---
