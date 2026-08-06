# Opentrons API Documentation Structure

This file provides detailed analysis of key files in the Opentrons Python API v2 documentation for LLM context understanding.

## Overview

This documentation covers the Opentrons Python API v2, used to write protocols for Opentrons robots (OT-2 and Flex/OT-3). The API allows users to control pipettes, modules, labware, and execute automated laboratory protocols.

## File-by-File Analysis

## docs/v2/index.rst

<about>
This file is the main index/welcome page for the Opentrons Python Protocol API documentation (v2), not a protocol file itself. It provides an overview of the API framework designed for writing automated biology lab protocols for both Flex (OT-3) and OT-2 robots. The page includes getting started guidance, links to tutorials and examples, and demonstrates the basic structure of protocols through simple liquid transfer examples for both robot types. The example protocols shown use 1-channel pipettes (flex_1channel_1000 for Flex, p300_single for OT-2), basic labware (96-well plates and tip racks), and demonstrate fundamental liquid handling steps: pick up tip, aspirate 100 µL from well A1, dispense to well B2, and drop tip. The documentation emphasizes that protocols should be readable like lab notebooks while allowing programmers to leverage Python's full capabilities for advanced automation.
</about>

---

## docs/v2/new_advanced_running.rst

<about>
This file documents advanced control methods for operating Opentrons robots outside of the standard app interface, focusing on two approaches: Jupyter Notebook and command-line execution. It explains how to use Jupyter Notebook (running on port 48888) to write and debug protocols interactively by restructuring them into cells rather than a single run function, and provides guidance on setting labware offsets manually since Labware Position Check cannot be performed outside the app. The documentation covers both OT-2 and Flex robots, includes examples using various pipette types (1-channel, 8-channel, 96-channel), and addresses special considerations for using modules (requiring the robot server to be stopped). It also explains how to execute protocols via command line using `opentrons_execute`, making it useful for scenarios requiring dynamic variables, CSV file integration, or partial protocol execution during development and debugging.
</about>

---

## docs/v2/new_modules.rst

<about>
This file is the main index page for the Hardware Modules section of the Opentrons API v2 documentation, not a protocol file. It provides an overview of both powered and unpowered hardware modules available for the Flex and OT-2 robots, including the Absorbance Plate Reader Module, Heater-Shaker Module, Magnetic Module, Temperature Module, Thermocycler Module (all powered), and the 96-well Magnetic Block (unpowered). The documentation explains that powered modules connect via USB and are automatically detected, while unpowered modules are recognized only when used in uploaded protocols. The file serves as a navigation hub, linking to detailed documentation for setting up modules with labware, working with individual module contexts, and managing multiple modules of the same type in a single protocol. It includes a note about coordinate deck slot naming conventions between Flex (e.g., "D1", "D2") and OT-2 (numeric slots) for API version compatibility.
</about>

---

## docs/v2/new_protocol_api.rst

<about>
This file is the API Version 2 Reference documentation for the Opentrons Python Protocol API, providing a comprehensive reference of classes and methods that make up the API. It's not a protocol file but rather the technical documentation that covers all major components including ProtocolContext, InstrumentContext, Labware classes (including TrashBin and WasteChute), Wells and Liquids (including the new LiquidClass), and all available modules (Absorbance Plate Reader, Heater-Shaker, Magnetic Block, Magnetic Module, Temperature Module, and Thermocycler). The documentation also includes useful types, error classes, and methods for executing and simulating protocols. This reference guide supports both OT-2 and Flex robots and covers all pipette types (1-channel, 8-channel, and 96-channel), though specific implementations depend on the actual protocol being written using these API components.
</about>

---

## docs/v2/new_pipette.rst

<about>
This file is the main index page for the Pipettes section of the Opentrons Python API documentation, not a protocol file. It serves as a navigation hub that introduces pipettes as configurable devices for liquid movement and outlines the four main topics covered in this documentation section: loading pipettes into protocols, pipette characteristics (movement speeds and deck navigation), partial tip pickup configurations for multi-channel pipettes, and volume modes for Flex 50 µL pipettes. The page mentions both Flex (OT-3) and OT-2 robot types and references multi-channel pipettes (implying 8-channel and potentially 96-channel) in the context of partial tip pickup, but doesn't specify modules, fixtures, adapters, labware, liquids, or specific protocol steps. It primarily functions as an organizational page that directs users to more detailed subsections about pipette functionality and configuration.
</about>

---

## docs/v2/new_examples.rst

<about>
This file provides ready-made protocol examples for Opentrons Flex and OT-2 robots, designed to help users learn and build upon basic liquid handling skills. The protocols demonstrate various liquid handling techniques including basic and advanced liquid transfers, loops for automation, creating multiple air gaps, serial dilutions, and plate mapping with automatic tip refilling. All examples use API level 2.20 and are compatible with both Flex (OT-3) and OT-2 robots, utilizing 1-channel pipettes (flex_1channel_1000 for Flex, p300_single_gen2 for OT-2). The protocols use standard labware including USA Scientific 12-well reservoirs, Corning 96-well plates, and appropriate tip racks for each robot type. While no modules, fixtures, adapters, or specific liquids are mentioned, the protocols demonstrate key steps like transferring 100 µL between wells, distributing liquids across rows, creating air gaps between samples, performing serial dilutions with mixing, and dispensing varying volumes across an entire plate.
</about>

---

## docs/v2/conf.py

<about>
This is a Sphinx configuration file (conf.py) for building the Opentrons Python Protocol API v2 documentation, not a protocol file. It configures various documentation build settings including extensions (autodoc, napoleon, sphinx-tabs), theme options (using alabaster theme with custom styling), version information (dynamically pulled from the API package), and output formats (HTML, LaTeX, man pages). The file sets up intersphinx mapping for Python documentation, configures OpenGraph metadata for social sharing, defines custom sidebar templates, and includes extensive nitpick ignore patterns to suppress warnings for internal/undocumented API references. It also sets up RST prolog substitutions for the current API level (2.23) and release version, making these values available throughout the documentation.
</about>

---

## docs/v2/tutorial.rst

<about>
This file is a comprehensive tutorial for creating Python protocols using the Opentrons API, guiding users through building a serial dilution protocol from scratch. The tutorial covers API version 2.16 and is designed for both Flex (OT-3) and OT-2 robots, with examples for both 1-channel and 8-channel pipettes (specifically the Flex 1-Channel 1000 µL and P300 Single-Channel GEN2 for examples). The protocol uses NEST 12 Well Reservoir 15 mL, NEST 96 Well Plate 200 µL Flat, and appropriate tip racks (Opentrons Flex Tips 200 µL or Opentrons 96 Tip Rack 300 µL). The serial dilution process involves three main steps: distributing diluent to all wells, adding solution to the first column, and performing stepwise dilution across the plate from column 1 to 12. The tutorial includes sections on metadata, requirements blocks, loading labware and pipettes, and using the transfer() method for complex liquid handling operations, concluding with instructions for both simulating and running the protocol on actual hardware.
</about>

---

## docs/v2/new_labware.rst

<about>
This file is API documentation for the labware functionality in the Opentrons Python API, not a protocol file. It provides comprehensive guidance on working with labware including loading default and custom labware, accessing wells, labeling liquids, and understanding well dimensions. The documentation covers both OT-2 and Flex (OT-3) robots and explains how to load labware onto deck slots or adapters, access individual wells or groups of wells through various methods (dictionary access, list access, rows, columns), and optionally define and label liquids in wells. It includes examples of loading lids on compatible plates and tip racks, loading labware on adapters (including heater-shaker module examples), and retrieving well properties like depth, diameter, length, and width. While the documentation references various labware types (96-well plates, tip racks, reservoirs) and mentions the heater-shaker module in adapter examples, it doesn't describe specific protocol steps or liquid handling operations, focusing instead on the foundational labware setup and access methods needed before performing liquid transfers.
</about>

---

## docs/v2/adapting_ot2_flex.rst

<about>
This file is documentation for adapting OT-2 Python protocols to run on Opentrons Flex robots. It provides a migration guide covering the minimal changes needed to convert OT-2 protocols for Flex compatibility, including updating metadata and requirements (API level 2.15+ and robotType: "Flex"), converting pipette and tip rack load names, adding trash bin loading, updating deck slot labels from numeric to coordinate format, and updating module load names. The documentation includes side-by-side code examples comparing original OT-2 code with updated Flex code, and specifically addresses the incompatibility of the Magnetic Module with Flex, suggesting the use of the Magnetic Block and Flex Gripper as alternatives. While not a protocol itself, the guide references various pipette types (1-channel, 8-channel) and modules (Temperature Module Gen2, Thermocycler Module Gen2, Heater-Shaker Module, and the incompatible Magnetic Module), and demonstrates protocol steps including liquid mixing, transferring, and plate movement using the gripper.
</about>

---

## docs/v2/runtime_parameters.rst

<about>
This file is documentation for the Runtime Parameters feature in the Opentrons Python API, not a protocol file. It serves as an index page that introduces runtime parameters - user-customizable variables that allow technicians to modify protocol behavior without editing code. The documentation outlines the structure of the runtime parameters section, including fundamentals (choosing, defining, and using parameters), practical use cases (sample count adjustment, dry run testing, and cherrypicking with CSV files), and style guidance for parameter authors. The file emphasizes that runtime parameters give protocol authors the ability to create flexible, user-friendly protocols while maintaining control over the user experience. It does not contain any specific protocol implementation, pipette configurations, modules, labware, or protocol steps - rather, it provides a roadmap to the detailed documentation pages that cover these topics in depth.
</about>

---

## docs/v2/moving_labware.rst

<about>
This file documents the "Moving Labware" functionality in the Opentrons Python API, explaining how to programmatically move labware between deck slots during protocol execution. It covers both automatic movement using the Flex Gripper and manual movement (requiring user intervention) on both Flex and OT-2 robots, with the gripper being exclusive to Flex. The documentation details supported labware for gripper movement including full-skirt PCR plates, NEST well plates, Opentrons Flex 96 tip racks (50µL, 200µL, 1000µL variants), and Opentrons lids. It explains movement with modules (requiring adapters and proper module states like open latches), movement to waste chutes, lid movement capabilities, and the special OFF_DECK location for removing/adding labware during protocols. While not a protocol itself, the documentation includes code examples showing the move_labware() method usage with various parameters and scenarios, emphasizing that manual moves are the default behavior unless use_gripper=True is specified.
</about>

---

## docs/v2/new_atomic_commands.rst

<about>
This file is part of the Opentrons API v2 documentation that provides an overview of the "Building Block Commands" section, which covers the fundamental commands that Opentrons robots can perform. It's not a protocol file but rather a documentation index page that introduces three main categories of basic robot commands: pipette tip handling, liquid control, and utility functions. The file serves as a table of contents linking to detailed documentation on picking up/dropping tips, aspirating/dispensing liquids, and various robot utilities like pausing protocols or controlling lights. It emphasizes that while these commands are basic, they are foundational to more complex commands and essential for protocol development. The documentation applies to both OT-2 and Flex robots and covers all pipette types (1-channel, 8-channel, and 96-channel), though specific details about modules, fixtures, adapters, labware, and liquids are not mentioned in this overview page.
</about>

---

## docs/v2/robot_position.rst

<about>
This file is API documentation for controlling robot positioning and movement in the Opentrons Python API, not a protocol file. It provides comprehensive guidance on how to define positions within the robot workspace and control pipette movements, including positioning relative to labware wells (top, bottom, center, meniscus), trash containers, and deck coordinates. The documentation covers both OT-2 and Flex (OT-3) robots, with some features being Flex-specific (like liquid meniscus detection and collision detection), and references movement control for all pipette types (1-channel, 8-channel, and 96-channel). While it uses generic labware references like "plate" in examples and mentions TrashBin and WasteChute fixtures for Flex, it doesn't specify particular modules, adapters, or liquids. The documented features include well positioning methods, default position adjustments, labware position check integration, independent pipette movement with move_to(), controlling movement speeds (both overall gantry speed and individual axis speeds), and working with Points and Locations for precise positioning control.
</about>

---

## docs/v2/versioning.rst

<about>
This file documents the versioning system for the Opentrons Python Protocol API, explaining how API versions are separate from robot software versions and how to specify versions in protocols. It covers the major/minor version numbering system, provides guidance on choosing appropriate API versions for protocols, and includes a comprehensive changelog detailing new features, improvements, and breaking changes introduced in each API version from 2.0 through 2.23. The documentation applies to both OT-2 and Flex robots, with version 2.15 introducing Flex support and subsequent versions adding Flex-specific features like partial tip pickup for 96-channel pipettes, waste chute/trash bin fixtures, and liquid presence detection. Notable features documented include support for various modules (Heater-Shaker, Magnetic Block, Absorbance Plate Reader), adapters, lids, runtime parameters, and improved liquid handling capabilities, though this is not a protocol file but rather API reference documentation.
</about>

---

## docs/v2/deck_slots.rst

<about>
This file documents deck slot specifications and deck configuration for the Opentrons Python Protocol API, explaining how to specify locations when loading labware, modules, and other items onto the robot deck. It covers both Flex and OT-2 robots, detailing their different labeling systems (Flex uses coordinates A1-D4, OT-2 uses numbers 1-11) and how these formats are interchangeable in API version 2.15+. The documentation extensively covers Flex-specific deck configuration features including staging area slots (A4-D4), trash bins (loaded with `load_trash_bin()` in API 2.16+), and the waste chute (loaded with `load_waste_chute()` in slot D3). It explains deck conflicts that can occur between fixtures and modules, and provides guidance on resolving these conflicts either by physically rearranging hardware or modifying the protocol. While this is not a protocol file, it references various API methods like `load_labware()`, `move_labware()`, and mentions compatibility with different pipette types (1-, 8-, and 96-channel) when using features like the waste chute.
</about>

---

## docs/v2/new_complex_commands.rst

<about>
This file is documentation for complex liquid handling commands in the Opentrons Python API v2, not a protocol file. It serves as an introduction to three advanced methods (transfer, distribute, and consolidate) that combine multiple basic commands into single method calls for handling larger groups of wells and repetitive actions. The documentation explains that these complex commands integrate tip-handling behavior and can perform additional actions like adding air gaps, knocking droplets, mixing, and blowing out excess liquid. It references three sub-pages covering sources/destinations, order of operations, and parameters for these complex commands. The file doesn't specify robot types, pipette configurations, modules, fixtures, adapters, labware, or liquids as it's a high-level overview document that directs readers to more detailed documentation pages.
</about>

---

## docs/v2/example_protocols/dilution_tutorial.py

<about>
This file is a complete serial dilution protocol for the Opentrons OT-2 robot using a single-channel pipette, created as the outcome of following the Python Protocol API Tutorial. The protocol uses API level 2.16 and is designed for the OT-2 robot type, employing a p300_single_gen2 (single-channel 300 µL pipette) mounted on the left mount. The protocol uses three labware items: opentrons_96_tiprack_300ul in position 1, nest_12_reservoir_15ml in position 2, and nest_96_wellplate_200ul_flat in position 3. The protocol performs a serial dilution by first distributing 100 µL of diluent from reservoir well A1 to all wells of the 96-well plate, then for each of the 8 rows, transfers 100 µL of solution from reservoir well A2 to the first well of each row with mixing (3 times, 50 µL), and finally performs serial dilutions by transferring 100 µL from each well to the next well in the row (columns 1-11 to columns 2-12) with mixing after each transfer.
</about>

---

## docs/v2/example_protocols/dilution_tutorial_flex.py

<about>
This file is a complete serial dilution protocol for the Opentrons Flex robot using a 1-channel pipette, created as the outcome of following the Python Protocol API Tutorial. The protocol uses API level 2.16 and is designed for the Flex (OT-3) robot type, employing a flex_1channel_1000 (1-channel 1000 µL pipette) mounted on the left mount. The protocol uses three labware items: opentrons_flex_96_tiprack_200ul in position D1, nest_12_reservoir_15ml in position D2, and nest_96_wellplate_200ul_flat in position D3, plus a trash bin fixture in position A3. The protocol performs a serial dilution by first distributing 100 µL of diluent from reservoir well A1 to all wells of the 96-well plate, then for each of the 8 rows, transfers 100 µL of solution from reservoir well A2 to the first well of each row with mixing (3 times, 50 µL), and finally performs serial dilutions by transferring 100 µL from each well to the next well in the row (columns 1-11 to columns 2-12) with mixing after each transfer.
</about>

---

## docs/v2/example_protocols/dilution_tutorial_multi_flex.py

<about>
This file is a serial dilution tutorial protocol for the Opentrons Flex robot using an 8-channel pipette, demonstrating the outcome of following the Python Protocol API Tutorial. The protocol uses API level 2.16 and is designed for the Flex (OT-3) robot type, employing a flex_8channel_1000 pipette mounted on the right side. The protocol uses three labware items: opentrons_96_tiprack_300ul for tips, nest_12_reservoir_15ml for the reservoir, and nest_96_wellplate_200ul_flat for the dilution plate, along with a trash bin fixture. The protocol performs a serial dilution by first distributing 100 µL of diluent from reservoir well A1 to all wells in the first row of the plate, then transferring 100 µL of solution from reservoir well A2 to the first well of the row with mixing, and finally performing stepwise dilutions by transferring 100 µL from each well to the next well in the row (columns 1-11 to columns 2-12) with mixing after each transfer.
</about>

---

## docs/v2/example_protocols/dilution_tutorial_multi.py

<about>
This file is a serial dilution protocol for the OT-2 robot using an 8-channel pipette, created as the outcome of following the Python Protocol API Tutorial. It's a protocol file with API level 2.16 that performs a stepwise dilution across a 96-well plate. The protocol uses an 8-channel P300 Gen2 pipette mounted on the right side. No modules, fixtures, or adapters are used. The labware includes an Opentrons 96-tip rack (300µL), a NEST 12-well reservoir (15mL), and a NEST 96-well plate (200µL flat bottom). While specific liquids aren't named, the protocol references diluent in reservoir well A1 and sample solution in reservoir well A2. The protocol steps include: (1) distributing 100µL of diluent to all wells in the first row of the plate, (2) transferring 100µL of sample solution from the reservoir to the first well of the row with mixing, and (3) performing serial dilution by transferring 100µL from each well to the next across 11 wells in the row, mixing after each transfer.
</about>

---

## docs/v2/basic_commands/pipette_tips.rst

<about>
This file is API documentation for pipette tip manipulation commands in the Opentrons Python API, not a protocol file. It provides comprehensive guidance on the three fundamental tip handling methods: pick_up_tip(), drop_tip(), and return_tip(), with code examples demonstrating basic usage and automation patterns. The documentation covers both OT-2 and Flex (OT-3) robots and references various pipette types (1-channel, 8-channel, and 96-channel) in the context of tip handling, with special notes about partial tip pickup restrictions for returning tips. While the examples use generic tip rack labware (like "opentrons_flex_96_tiprack_1000ul"), the file doesn't mention specific modules, fixtures, adapters, or liquids. The protocol steps documented include picking up tips (with automatic tracking), dropping tips (in trash or specific locations), returning tips to their original positions, and automating tip pickup through loops, with important notes about how the API tracks used versus unused tips.
</about>

---

## docs/v2/basic_commands/utilities.rst

<about>
This file is API documentation for utility commands in the Opentrons Python API, not a protocol file. It provides guidance on robot utility features including protocol delays and pauses, homing operations for the gantry and pipettes, adding comments to protocols, controlling rail lights, and checking the OT-2 door safety switch status. The documentation covers both OT-2 and Flex robots, with the door safety switch being OT-2-specific and introduced in robot software version 3.19. While the examples reference loading pipettes (specifically mentioning a "flex_1channel_1000" in homing examples), the documentation doesn't specify particular modules, fixtures, adapters, labware, or liquids. The utility commands documented include delay (with seconds/minutes parameters), pause (with optional message), various homing methods (gantry, pipette Z-axis and plunger), comment display, rail light control (on/off), and door status checking for OT-2 robots.
</about>

---

## docs/v2/basic_commands/liquids.rst

<about>
This file is API documentation for liquid control methods in the Opentrons Python API, not a protocol file. It provides comprehensive guidance on liquid handling commands including aspirating, dispensing, mixing, creating air gaps, and detecting liquid presence, with code examples and best practices for each method. The documentation covers both OT-2 and Flex (OT-3) robots, with some features being Flex-specific (like liquid detection and measurement), and references 1-channel, 8-channel, and 96-channel pipettes, particularly in the push-out volume specifications. While the documentation uses generic labware references like "plate" and "reservoir" in examples, it doesn't mention specific modules, fixtures, adapters, or liquids. The protocol steps documented include aspirate (with various positioning options), dispense (with flow rate and push-out controls), blow out, touch tip, mix, air gap creation, and Flex-specific features for detecting/requiring liquid presence and measuring liquid height.
</about>

---

## docs/v2/complex_commands/order_operations.rst

<about>
This file documents the order of operations for complex liquid handling commands in the Opentrons Python API, explaining how commands like transfer(), distribute(), and consolidate() execute as a series of basic building block commands. It details the fixed sequence of up to 10 possible steps (pick up tip, mix at source, aspirate, touch tip at source, air gap, dispense, mix at destination, touch tip at destination, blow out, drop tip) and provides examples showing how different parameter combinations affect the execution order. The documentation covers automatic tip refilling behavior when liquid volumes exceed pipette capacity, and explains how to use lists of volumes to transfer different amounts to different wells or skip wells entirely. While not a protocol file itself, it references both single-channel pipettes (50 µL and 1000 µL examples) and mentions generic labware like plates and tip racks in its examples, with no specific modules, fixtures, adapters, or liquids mentioned.
</about>

---

## docs/v2/complex_commands/sources_destinations.rst

<about>
This file is API documentation for the Opentrons Python API's complex liquid handling commands, specifically covering the `transfer()`, `distribute()`, and `consolidate()` methods. It explains how these high-level commands handle liquid movement between multiple wells, with `transfer()` being the most versatile (allowing any number of source and destination wells), `distribute()` limiting to one source well and multiple destinations, and `consolidate()` limiting to multiple sources and one destination. The documentation details the different aspiration and dispensing patterns for each method, including how `transfer()` alternates between aspirating and dispensing, `distribute()` minimizes aspirations by filling the tip once and dispensing multiple times, and `consolidate()` aspirates multiple times before dispensing once. It also covers many-to-many transfer patterns, explaining how the API maps source wells to destination wells when lists of different sizes are provided, and discusses optimization strategies for reducing gantry movement and saving time. While this is reference documentation rather than a protocol, it mentions both OT-2 and Flex robots and references various pipette types (1-channel, 8-channel, 96-channel) in the context of optimizing liquid transfers, though it doesn't specify particular modules, fixtures, adapters, or labware beyond generic examples using plates and reservoirs.
</about>

---

## docs/v2/complex_commands/parameters.rst

<about>
This file documents complex liquid handling parameters for the Opentrons Python API, providing detailed explanations of optional parameters that control the behavior of complex commands like transfer(), distribute(), and consolidate(). The documentation covers parameters for tip handling (new_tip), mixing before/after operations, disposal volumes, touch tip actions, air gaps, blow out locations, and tip trash behavior, with extensive code examples showing how each parameter affects liquid handling operations. While not a protocol file itself, it references both OT-2 and Flex robots and mentions various pipette types (1-channel, 8-channel, 96-channel) in the context of parameter behavior, particularly noting capacity limitations and tip refilling strategies. The file uses generic labware references like "plate" and "reservoir" in examples but doesn't specify particular modules, fixtures, adapters, or liquids, focusing instead on how parameters modify the sequence of protocol steps including aspirating, dispensing, mixing, touching tips, creating air gaps, and managing tip usage throughout complex liquid handling operations.
</about>

---

## docs/v2/pipettes/volume_modes.rst

<about>
This file documents the volume modes feature for Flex 50 µL pipettes (both 1-channel and 8-channel) in the Opentrons API, explaining how to configure these pipettes for accurate dispensing of very small liquid volumes. The documentation describes the `configure_for_volume()` method introduced in API version 2.15, which switches between low-volume mode (1-4.9 µL) and regular mode (5-50 µL), affecting the pipette's minimum/maximum volumes and default push-out volumes. It provides code examples showing how to configure the pipette before liquid handling operations, emphasizes that the pipette must not contain liquid when changing modes, and demonstrates best practices for handling multiple volumes in a protocol using loops. The file is specific to Flex (OT-3) robots and their 50 µL pipettes, with no mention of modules, fixtures, adapters, or specific labware beyond generic plate references used in examples.
</about>

---

## docs/v2/pipettes/partial_tip_pickup.rst

<about>
This file is comprehensive API documentation for the partial tip pickup feature in Opentrons robots, not a protocol file. It explains how to configure multi-channel pipettes (8-channel and 96-channel) to use fewer tips than their full capacity, which is especially useful for the Flex 96-channel pipette that occupies both mounts. The documentation covers various nozzle layouts including column (API 2.16+), row (API 2.20+), single tip (API 2.20+), and partial column configurations (API 2.20+), with detailed code examples for each. It addresses both OT-2 and Flex robots, though some features are Flex-specific. The file includes important information about tip rack adapters (required for full 96-channel pickup but not for partial pickup), deck extent limitations, labware arrangement considerations to avoid collisions, and best practices for organizing tip racks when switching between full and partial pickup modes. While it references generic tip racks like "opentrons_flex_96_tiprack_1000ul" in examples, it doesn't specify particular modules, fixtures, liquids, or complete protocol steps beyond the configuration and tip pickup operations.
</about>

---

## docs/v2/pipettes/loading.rst

<about>
This file is API documentation for loading pipettes in the Opentrons Python protocol API, not a protocol file itself. It provides comprehensive guidance on how to load and configure pipettes for both Flex (OT-3) and OT-2 robots, including API load names for all available pipette models (1-channel, 8-channel, and 96-channel variants). The documentation covers loading pipettes with their associated tip racks, configuring trash containers, and enabling liquid presence detection (a Flex-specific feature). While it includes code examples showing how to load pipettes and tip racks (using generic tiprack labware like "opentrons_flex_96_tiprack_1000ul"), it doesn't describe a complete protocol or mention specific modules, fixtures, adapters, or liquids. The file also details advanced features like automatic tip tracking, custom trash container assignment, and global liquid presence detection settings that can be toggled on and off during protocol execution.
</about>

---

## docs/v2/pipettes/characteristics.rst

<about>
This file documents the fundamental characteristics and capabilities of Opentrons pipettes, covering multi-channel movement patterns, flow rates, and pipette generations. It explains how multi-channel pipettes (8-channel and 96-channel) use their primary channel (back-left) as a reference point for movement, with specific well access limitations based on channel count and plate type. The documentation provides detailed flow rate specifications for both Flex and OT-2 pipettes, showing default aspirate/dispense/blow-out rates in µL/s for different pipette models and tip capacities, and explains how to modify these rates programmatically. It also covers backward compatibility between OT-2 GEN2 and GEN1 pipettes, noting volume range overlaps and exceptions. While not a protocol file, the documentation includes code examples demonstrating pipette movement and flow rate control for both robot types (OT-2 and Flex), referencing standard labware like 96-well and 384-well plates, but doesn't specify modules, fixtures, adapters, or specific liquids.
</about>

---

## docs/v2/parameters/using_values.rst

<about>
This file is documentation for using runtime parameters in Opentrons Python protocols, not a protocol file itself. It explains how to access and manipulate parameter values within the `run()` function through the `params` object, covering different parameter types (boolean, integer, float, and CSV) and their usage. The documentation provides examples of accessing parameter attributes like `params.dry_run`, `params.sample_count`, and `params.volume`, with special attention to CSV parameter handling through the `CSVParameter` class that offers three access methods: as a file handler, as a string, or as nested lists via `parse_as_csv()`. It also outlines limitations of parameters, noting they cannot affect import statements, robot type selection, API version, metadata, or other runtime parameters, and explains that parameter values are applied through protocol reanalysis which affects timing-dependent operations like labware offset application. The documentation includes practical tips for type casting and error handling, particularly for CSV parameters that lack default values.
</about>

---

## docs/v2/parameters/choosing.rst

<about>
This file provides guidance on choosing effective parameters for Opentrons Python protocols, focusing on best practices for parameterization rather than being a protocol itself. It discusses three key goals when adding parameters: adding flexibility for run-to-run variations, working efficiently without overwhelming users with choices, and avoiding errors by ensuring all parameter combinations produce valid protocols. The document uses examples like serial dilution protocols and pipette mount configurations to illustrate how to build parameters around core scientific tasks, avoid contradictory inputs, and set appropriate boundaries for numerical parameters. It emphasizes the importance of reasoning through user choices to prevent nonsensical outcomes and suggests collapsing multiple related questions into single parameters when possible to reduce complexity and potential errors.
</about>

---

## docs/v2/parameters/use_case_cherrypicking.rst

<about>
This file documents a parameter use case for cherrypicking in Opentrons Python protocols, demonstrating how to use CSV runtime parameters to automate liquid transfers from specific source wells to destination wells. The example protocol is for a Flex robot (API level 2.20 or higher) using a 1-channel 1000 µL pipette. The protocol uses Opentrons 96-well PCR plates (200 µL full skirt) for both source and destination labware, along with a 1000 µL tip rack and trash bin. The CSV parameter controls source slot, source well, and transfer volume, allowing technicians to customize cherrypicking operations without modifying the Python code. The documented protocol steps include parsing CSV data, dynamically loading source labware based on CSV content, and performing parameterized liquid transfers using the parsed data in a loop that maps source locations to sequential destination wells.
</about>

---

## docs/v2/parameters/use_case_dry_run.rst

<about>
This file is a use case documentation for implementing a dry run parameter in Opentrons Python protocols, not a protocol file itself. It provides detailed guidance on how to add a Boolean parameter that allows users to perform test runs without handling actual samples or reagents. The documentation demonstrates how a single dry run parameter can control three main behaviors: skipping module actions and delays (including Thermocycler operations), reducing mix repetitions from 10 to 1 to save time, and returning tips to their racks instead of disposing them in trash. While the file references both OT-2 and Flex robots through mentions of tip handling and gripper usage, it doesn't specify particular pipette types, modules (except for a Thermocycler example), fixtures, adapters, labware, or liquids. The protocol steps mentioned include delays, thermocycler operations (setting temperatures, executing PCR profiles), mixing steps, tip handling (pick up, return, drop), and labware movement, all shown as conditional operations based on the dry run parameter value.
</about>

---

## docs/v2/parameters/style.rst

<about>
This file is a style guide for writing parameters in Opentrons Python protocols, not a protocol file itself. It provides comprehensive guidance on how to write clear, consistent parameter names and descriptions when defining runtime parameters (RTP) in protocols. The guide covers general principles like using nouns for parameter names, writing action-oriented descriptions, using sentence case, and ordering choices logically. It also includes type-specific guidance for Boolean parameters (avoiding double negatives, using "On/Off" terminology), numeric choice parameters (not repeating text in choices, using ranges when appropriate), and string parameters (avoiding yes/no synonyms when Boolean would be better). The document emphasizes clarity and consistency to improve the user experience for technicians running protocols, with numerous examples of good and bad practices marked with ✅ and ❌ symbols.
</about>

---

## docs/v2/parameters/use_case_sample_count.rst

<about>
This file documents a comprehensive use case for implementing sample count parameters in Opentrons protocols, demonstrating how a single parameter can affect multiple aspects of protocol execution. The example is adapted from an actual DNA prep protocol that uses 8-channel pipettes to process 8, 16, 24, or 32 samples on a Flex robot. The protocol uses both 50 µL and 200 µL tip racks, a Heater-Shaker Module with an adapter (opentrons_96_pcr_adapter), various labware including a NEST 12-well reservoir and Opentrons 96-well PCR plate, and multiple liquids (AMPure Beads, Tagmentation Stop, Tagmentation Wash Buffer, and samples). The documentation explains how the sample count parameter influences tip rack loading calculations, reagent volume calculations, sample processing loops, and tip replenishment strategies, with code examples showing how to dynamically adjust these elements based on the chosen sample count. Key protocol steps mentioned include liquid loading, sample labeling, tagmentation stop addition, and sample transfers between different plate columns.
</about>

---

## docs/v2/parameters/defining.rst

<about>
This file documents how to define parameters in Opentrons Python protocols, providing a comprehensive guide on creating runtime parameters (RTP) that allow users to customize protocol behavior during run setup. The documentation explains the `add_parameters()` function and covers five parameter types: Boolean, integer, float, string, and CSV file parameters (added in version 2.20). Each parameter type has specific attributes including variable_name, display_name, description, default values, and type-specific options like minimum/maximum ranges or predefined choices. The file includes code examples for each parameter type, showing how to define them with appropriate constraints and user-friendly display options. This is not a protocol file itself but rather API documentation that helps protocol developers create flexible, user-configurable protocols that can be adjusted at runtime through the Opentrons App or Flex touchscreen interface.
</about>

---

## docs/v2/modules/heater_shaker.rst

<about>
This file is documentation for the Heater-Shaker Module in the Opentrons Python API, not a protocol file. It provides comprehensive guidance on using the Heater-Shaker Module, which can heat samples from 37-95°C and shake from 200-3000 rpm. The documentation covers deck placement restrictions for both OT-2 and Flex robots, with specific limitations on OT-2 regarding adjacent module placement, tall labware restrictions, and 8-channel pipette movement constraints. It details how to control the module's labware latch, load various thermal adapters (Universal Flat, 96 PCR, 96 Deep Well, and 96 Flat Bottom adapters), and compatible labware combinations. The documentation explains both blocking and non-blocking command execution for heating and shaking operations, with code examples showing how to set temperatures and shake speeds, manage timing, and deactivate the module. While this is API documentation rather than a specific protocol, it references various labware types and provides example code snippets for common operations like temperature control and orbital shaking.
</about>

---

## docs/v2/modules/magnetic_module.rst

<about>
This file documents the Magnetic Module for the OT-2 robot, which controls permanent magnets that can move vertically to create magnetic fields for magnetic bead-based protocols. The documentation covers the MagneticModuleContext API for engaging (raising) and disengaging (lowering) magnets, with examples showing a Magnetic Module GEN2 loaded in slot 6. It lists compatible 96-well PCR plates and deep well plates from the Opentrons Labware Library, including NEST, Bio-Rad, Thermo Scientific Nunc, and USA Scientific plates. The module supports height customization through `height_from_base` and `offset` parameters when engaging magnets, with the GEN2 version using smaller magnets that require 5-7 minute attraction times depending on liquid volume. The documentation notes that adapter magnets are available for applications requiring additional magnetic strength, and emphasizes that the module must be manually deactivated after protocol completion.
</about>

---

## docs/v2/modules/temperature_module.rst

<about>
This file documents the Temperature Module for Opentrons robots, providing comprehensive guidance on using this heating and cooling device that can control temperatures between 4°C and 95°C. The documentation covers how to load the Temperature Module (both GEN1 and GEN2 versions) in Python protocols, including methods for loading various adapters and labware combinations. It details three types of labware configurations: standalone adapters (aluminum flat bottom plate, 96-well aluminum block, and 96 deep well adapter), 24-well block-and-tube combinations for various tube types (0.5-2mL), and legacy 96-well block-and-plate combinations. The file explains temperature control methods including `set_temperature()` for setting target temperatures and `deactivate()` for stopping temperature control, as well as how to check the module's status. While not a protocol itself, the documentation provides code examples compatible with API version 2.0 and later, with specific features added in versions 2.3 and 2.15, and applies to both OT-2 and Flex robots without specifying particular pipettes or liquids.
</about>

---

## docs/v2/modules/thermocycler.rst

<about>
This file is API documentation for the Thermocycler Module in the Opentrons Python API, not a protocol file. It provides comprehensive guidance on controlling the Thermocycler Module's lid, block temperature, and temperature profiles for automated thermocycling operations. The documentation covers both GEN1 and GEN2 Thermocycler modules, with the GEN2 having a plate lift feature for easier plate removal. The module can heat the block between 4-99°C and the lid up to 110°C. Key features documented include lid control (open/close and temperature settings), block temperature control with hold times and volume adjustments, and creating/executing temperature profiles for PCR and other heat-sensitive reactions. The documentation also covers the use of auto-sealing lids with the Flex robot and gripper, including the Opentrons Tough PCR Auto-sealing Lid and Flex Deck Riser adapter. Example labware mentioned includes "opentrons_96_wellplate_200ul_pcr_full_skirt" for PCR plates. While specific pipettes and liquids aren't mentioned, the documentation focuses on the module's temperature control capabilities and integration with automated liquid handling workflows.
</about>

---

## docs/v2/modules/magnetic_block.rst

<about>
This file documents the Magnetic Block module for the Opentrons Flex robot, which is an unpowered 96-well plate with high-strength neodymium magnets for magnetic bead-based protocols. The documentation explains that unlike powered modules, the Magnetic Block is not directly controlled by the robot or app, but rather manipulated through protocol commands to load labware onto it and use the Flex Gripper to move labware on and off the module. The file provides code examples showing how to load the Magnetic Block in a deck slot using the MagneticBlockContext object, load labware (specifically a biorad_96_wellplate_200ul_pcr plate) onto the module, and move that labware using the Flex Gripper. This module is exclusively compatible with the Flex robot (not OT-2) and was added in API version 2.15.
</about>

---

## docs/v2/modules/setup.rst

<about>
This file is API documentation for module setup in the Opentrons Python API, not a protocol file. It provides comprehensive guidance on how to load and configure hardware modules (Temperature Module, Magnetic Module, Thermocycler, Heater-Shaker, Magnetic Block, and Absorbance Plate Reader) onto the robot deck and how to load labware onto these modules. The documentation covers both OT-2 and Flex robots, showing code examples for loading modules using the `load_module()` method with appropriate API load names and deck locations. It includes a detailed table of available modules with their API load names and the API versions in which they were introduced (ranging from 2.0 to 2.21). The file also explains how to load labware onto modules using the module context's `load_labware()` method, discusses module-labware compatibility considerations, and mentions that custom labware with proper stacking offsets can be used with module adapters. While it references generic labware like the Opentrons 24 Well Aluminum Block in examples, it doesn't specify particular pipettes, liquids, or protocol steps beyond the module and labware loading procedures.
</about>

---

## docs/v2/modules/multiple_same_type.rst

<about>
This file documents how to use multiple modules of the same type within a single Opentrons protocol, explaining that modules load based on their USB port number rather than deck location. The documentation covers both Flex (OT-3) and OT-2 robots, showing example code for loading multiple Temperature Module Gen2 units in different deck slots, with the module connected to the lowest USB port number loading first. While not a complete protocol, the examples demonstrate the module loading syntax for both robot types, with the Flex example showing modules in slots D1 and C1 (USB ports 2 and 6), and the OT-2 example showing modules in slots 1 and 3 (USB ports 1 and 2). The documentation notes that the Thermocycler Module is an exception that cannot be used in multiples due to its size, and recommends using the Opentrons App module controls to verify commands are being sent to the expected modules.
</about>

---

## docs/v2/modules/absorbance_plate_reader.rst

<about>
This file documents the Absorbance Plate Reader Module for the Opentrons Flex robot (API version 2.21+), which is an on-deck microplate spectrophotometer that measures sample concentrations in 96-well plates using light absorbance. The module can only be loaded in slots A3-D3 and uses the Flex Gripper to control its lid, with the detection unit in deck column 3 and a staging area for the lid in column 4. The documentation covers the complete workflow: closing the lid, initializing the reader (supporting wavelengths 450nm, 562nm, 600nm, and 650nm in single or multi-mode with optional reference wavelength), opening the lid, moving a plate onto the module, closing the lid again, and reading the plate. The module outputs optical density (OD) values from 0.0 to 4.0 as either a nested dictionary for in-protocol use or a CSV file for post-run analysis, with the CSV containing a 9x12 grid matching the plate layout plus metadata about wavelengths, serial number, and timestamps.
</about>

---

## src/opentrons/protocol_api/module_contexts.py

<about>
This file defines the module context classes for the Opentrons Protocol API, providing interfaces for controlling various hardware modules including Temperature Module, Magnetic Module, Thermocycler, Heater-Shaker, Magnetic Block, Absorbance Reader, and Flex Stacker. It's not a protocol file but rather core API infrastructure that enables protocol developers to interact with these modules through methods like temperature control, lid operations, shaking, magnetic engagement, and labware management. The file supports both OT-2 and Flex robots with API version-specific features, and while it doesn't directly use pipettes, it provides the foundation for loading labware and adapters onto modules that protocols would then access with pipettes. The module contexts handle operations like setting temperatures, engaging magnets, running thermocycler profiles, controlling the heater-shaker's speed and temperature, reading absorbance values, and managing the Flex Stacker's labware storage and retrieval operations.
</about>

---

## src/opentrons/protocol_api/\_types.py

<about>
This file defines type constants and enumerations used throughout the Opentrons Protocol API. It contains three main enum classes: `OffDeckType` (with a single value `OFF_DECK` used to indicate labware not currently on the robot's deck), `PlungerPositionTypes` (defining plunger positions: top, bottom, blow_out, and drop_tip), and `PipetteActionTypes` (defining pipette actions: aspirate, dispense, and blowout). The file exports these enums as Final constants for use in protocol development, with special documentation added for the `OFF_DECK` constant to explain its use with `ProtocolContext.move_labware()`. This is not a protocol file but rather a foundational type definition file that supports the API's type system.
</about>

---

## src/opentrons/protocol_api/robot_context.py

<about>
This file defines the `RobotContext` class, which is part of the Opentrons Protocol API (version 2.20+) and provides low-level control over robot motor axes and movement systems. It's not a protocol file but rather a core API component that allows direct control of robot motors, including moving to absolute positions, controlling the gripper jaw, and moving individual pipette motors. The class supports both OT-2 and Flex (OT-3) robots and can work with all pipette types (1-channel, 8-channel, and 96-channel), with specific handling for 96-channel pipettes in axis mapping. The file includes methods for moving mounts (left, right, extension/gripper), moving axes to absolute or relative positions, opening/closing the gripper jaw, building axis maps from locations, and converting plunger volumes/positions to axis coordinates. No specific modules, fixtures, adapters, labware, or liquids are mentioned as this is infrastructure code rather than a protocol implementation.
</about>

---

## src/opentrons/protocol_api/config.py

<about>
This file (`config.py`) is a configuration module for the Opentrons Protocol API that defines a simple `Clearances` class for managing default aspirate and dispense clearance values. The class provides properties with getters and setters to control the clearance distances (in what appears to be millimeters) that the pipette maintains above the bottom of wells during aspirate and dispense operations. This is not a protocol file but rather a supporting configuration class used by the Protocol API infrastructure. The file doesn't specify robot types, pipettes, modules, fixtures, adapters, labware, liquids, or protocol steps - it simply provides a data structure for storing and managing clearance configuration values.
</about>

---

## src/opentrons/protocol_api/deck.py

<about>
This file defines the `Deck` class in the Opentrons Protocol API, which provides a dictionary-like interface for accessing and managing items (labware and modules) loaded on the robot's deck. It's not a protocol file but rather a core API component that supports both OT-2 and Flex robots, handling deck slot management including standard deck slots and staging slots (available from API version 2.16+). The class allows users to get, delete (from API v2.15+), and iterate through deck items, while also providing utility methods for spatial relationships between slots (left_of, right_of), position calculations, and calibration point access. The file doesn't specify particular pipettes, modules, fixtures, adapters, labware, or liquids as it's an infrastructure component rather than a protocol implementation.
</about>

---

## src/opentrons/protocol_api/\_liquid_properties.py

<about>
This file (`_liquid_properties.py`) is a core component of the Opentrons Protocol API that defines data structures and classes for managing liquid handling properties in liquid class definitions. It provides a comprehensive object model for representing various liquid handling parameters including aspirate properties, dispense properties (both single and multi-dispense), and associated behaviors like submerge/retract movements, delays, touch tip, mixing, and blowout operations. The file includes a `LiquidHandlingPropertyByVolume` class that enables volume-dependent parameter interpolation, allowing properties to vary based on liquid volume. It also contains builder functions to convert between shared data models and the API's internal representations. This is not a protocol file but rather infrastructure code that supports the liquid class feature, enabling users to define custom liquid handling behaviors for different liquid types and optimize pipetting performance.
</about>

---

## src/opentrons/protocol_api/module_validation_and_errors.py

<about>
This file contains validation functions and error classes specifically for the Heater-Shaker module in the Opentrons Protocol API. It defines temperature and speed validation constraints for the Heater-Shaker module, with temperature limits of 37-95°C and speed limits of 200-3000 RPM. The file includes two custom exception classes (InvalidTargetTemperatureError and InvalidTargetSpeedError) and two validation functions that check if temperature and speed values fall within the acceptable ranges, raising appropriate errors with descriptive messages when values are out of bounds. This is not a protocol file but rather a utility module for ensuring safe operation of the Heater-Shaker module.
</about>

---

## src/opentrons/protocol_api/**init**.py

<about>
This file is the main `__init__.py` file for the Opentrons Protocol API package, serving as the entry point that defines and exports all the public-facing classes, functions, and constants that users can access when writing protocols. It imports and exposes core components including the ProtocolContext (main protocol interface), various module contexts (ThermocyclerContext, MagneticModuleContext, TemperatureModuleContext, HeaterShakerContext, MagneticBlockContext, AbsorbanceReaderContext, FlexStackerContext), instrument and labware interfaces (InstrumentContext, Labware, Well), disposal locations (TrashBin, WasteChute), liquid handling classes, parameter handling, and various constants for pipette control and deck positioning. The file supports both OT-2 and Flex robots with API versions ranging from MIN_SUPPORTED_VERSION to MAX_SUPPORTED_VERSION, and includes support for all pipette types (1-channel, 8-channel, 96-channel) through the nozzle layout constants (SINGLE, COLUMN, ROW, ALL). This is not a protocol file but rather the foundational API module that protocol files would import from to access Opentrons functionality.
</about>

---

## src/opentrons/protocol_api/\_parameter_context.py

<about>
This file defines the `ParameterContext` class, which is part of the Opentrons Protocol API's internal parameter system for Python protocols. It provides methods for defining runtime parameters that users can configure when running protocols, including integer, float, boolean, string, and CSV file parameters. The class handles parameter validation, stores parameter definitions, and provides methods to set parameter values from user overrides and export parameters for both protocol analysis and execution. This is not a protocol file but rather an internal API component that enables protocol authors to create configurable protocols with user-defined parameters. The file includes support for CSV file parameters (requiring API version 2.20 or higher) with a limitation of one CSV parameter per protocol, and provides functionality to initialize CSV files with their content and metadata.
</about>

---

## src/opentrons/protocol_api/labware.py

<about>
This file (`labware.py`) is a core module in the Opentrons Protocol API that provides classes and functions for labware handling, including the `Labware` and `Well` classes that encapsulate labware instances and their wells. It contains functionality for transforming symbolic labware points (like "well A1") to deck coordinates, loading and saving labware definitions, managing labware calibration offsets, and tracking tips in tip racks. The module supports both legacy and engine-based protocol cores, with API version-specific features ranging from 2.0 to 2.24, and includes methods for liquid tracking, well access patterns (by name, rows, columns), geometric calculations, and labware positioning. While not a protocol itself, this module is fundamental infrastructure used by all protocols to interact with labware on both OT-2 and Flex robots, supporting various labware types including plates, tip racks, reservoirs, and adapters, with special handling for features like tip tracking, liquid volume management, and meniscus-based liquid handling operations.
</about>

---

## src/opentrons/protocol_api/\_transfer_liquid_validation.py

<about>
This file is not a protocol but rather an internal validation module for the Opentrons API that handles transfer liquid operations. It provides validation and normalization functionality for liquid transfer arguments, ensuring that source and destination wells are valid, tip policies are properly configured, and trash locations are appropriate. The module works with both single and multi-channel pipettes (as evidenced by the `group_wells_for_multi_channel` parameter) and supports both OT-2 and Flex robots through its handling of TrashBin and WasteChute disposal locations (WasteChute being Flex-specific). The file doesn't specify particular labware, liquids, modules, fixtures, or adapters, but it validates that wells can accept liquid transfers and ensures proper tip rack configuration based on the transfer policy. The main function `verify_and_normalize_transfer_args` performs comprehensive validation including checking for existing tips when using "NEVER" tip policy, ensuring the pipette starts with no liquid, and grouping wells appropriately for multi-channel transfers.
</about>

---

## src/opentrons/protocol_api/create_protocol_context.py

<about>
This file is not a protocol but rather a factory module for creating ProtocolContext instances in the Opentrons API. It provides the `create_protocol_context()` function which initializes protocol contexts with different core implementations based on the API version specified. The module supports both OT-2 and Flex robot types through its deck_type parameter and handles the transition between legacy protocol cores (for older API versions) and the newer Protocol Engine-based cores (for API version 2.14 and above). It manages hardware control interfaces, labware offset providers, and protocol engine integration, with special handling for loading fixed trash areas on OT-2 robots when using newer API versions. The file doesn't directly use pipettes, modules, fixtures, adapters, labware, or liquids, nor does it define protocol steps - instead, it creates the foundational context object that protocols use to access these features.
</about>

---

## src/opentrons/protocol_api/protocol_context.py

<about>
This file is the core implementation of the ProtocolContext class in the Opentrons Python Protocol API, which serves as the main interface for writing and executing protocols on both OT-2 and Flex (OT-3) robots. It provides methods for loading instruments (1-channel, 8-channel, and 96-channel pipettes), labware, adapters, and various modules (Temperature, Magnetic, Thermocycler, Heater-Shaker, Magnetic Block, Absorbance Reader, and Flex Stacker), as well as controlling protocol flow with commands like pause, delay, and comment. The class supports API versions from 2.0 onwards and includes robot-specific features like trash bins, waste chutes, lid stacking, and liquid class definitions. While this is not a protocol file itself but rather the API implementation, it enables protocol creation by providing methods for deck management, instrument control, module loading, labware movement (including gripper support on Flex), and various protocol execution controls. The file handles version compatibility, robot type validation, and provides access to robot hardware features like rail lights and door status.
</about>

---

## src/opentrons/protocol_api/\_liquid.py

<about>
This file defines the core data structures for handling liquids and liquid classes in the Opentrons Protocol API. It contains two main classes: `Liquid`, a simple dataclass for representing basic liquid properties (name, description, display color), and `LiquidClass`, a more complex class that manages liquid handling properties specific to different pipette and tip combinations. The `LiquidClass` includes factory methods for creation from schema definitions, methods to update and retrieve transfer properties for specific pipette-tip combinations, and internal logic for handling both `InstrumentContext` objects and string representations of pipettes and tip racks. This is not a protocol file but rather part of the API's internal implementation for managing liquid-specific parameters and behaviors during liquid handling operations.
</about>

---

## src/opentrons/protocol_api/disposal_locations.py

<about>
This file defines disposal location classes for the Opentrons Protocol API, specifically `TrashBin` and `WasteChute` classes that represent physical disposal areas on the robot deck. It is not a protocol file but rather infrastructure code that enables protocols to interact with trash bins (on both OT-2 and Flex robots) and waste chutes (Flex-only). The file includes hardcoded fixture names for these disposal locations and provides methods to specify offsets for precise positioning when disposing of tips or liquids. Both classes implement a `_DisposalLocation` protocol interface and include a `top()` method (requiring API version 2.18+) that allows users to add x, y, and z offsets to the disposal location. The classes also expose internal properties like `area_name`, `height`, and `location` for Opentrons internal use, with the waste chute specifically located at deck slot D3.
</about>

---

## src/opentrons/protocol_api/\_parameters.py

<about>
This file (`_parameters.py`) is not a protocol file but rather an internal API implementation file that defines the `Parameters` class for handling protocol parameters in the Opentrons Python API. The class manages user-defined parameters by storing them in a dictionary, preventing parameter overwrites, and validating parameter names to ensure they don't conflict with existing attributes, reserved functions, or Python built-ins. It provides methods to initialize parameters, retrieve all parameter values, and includes safeguards against naming conflicts through custom `__setattr__` implementation and the `_initialize_parameter` method that raises `ParameterNameError` for invalid parameter names.
</about>

---

## src/opentrons/protocol_api/\_nozzle_layout.py

<about>
This file defines the `NozzleLayout` enum for the Opentrons Protocol API, which specifies different nozzle configuration types for pipettes. It is not a protocol file but rather an internal API component that defines six nozzle layout options: COLUMN (for full single column pickup, primarily for 96-channel pipettes), PARTIAL_COLUMN, SINGLE, ROW, QUADRANT, and ALL (which resets to default maximum tip capacity). The file creates both enum values and module-level constants for easier access, and includes documentation strings for COLUMN and ALL configurations that reference their use with the `InstrumentContext.configure_nozzle_layout()` method. This enum is particularly relevant for multi-channel pipettes (8-channel and 96-channel) where different nozzle configurations can be used for various liquid handling strategies.
</about>

---

## src/opentrons/protocol_api/instrument_context.py

<about>
This file is the core implementation of the InstrumentContext class in the Opentrons Python Protocol API, which provides the interface for controlling pipettes in protocols. It's not a protocol file but rather the API implementation that enables pipette operations like aspirating, dispensing, mixing, picking up tips, and more advanced features. The file supports both OT-2 and Flex (OT-3) robots and handles 1-channel, 8-channel, and 96-channel pipettes, with specific features like partial nozzle configuration for multi-channel pipettes introduced in later API versions. While it doesn't directly use modules, fixtures, or adapters, it provides methods to interact with various labware types and disposal locations (TrashBin, WasteChute). The implementation includes liquid handling capabilities with features like liquid presence detection, liquid height measurement, and advanced transfer methods with liquid classes (API 2.23+). Key protocol steps implemented include pick_up_tip, aspirate, dispense, mix, blow_out, drop_tip, touch_tip, air_gap, and complex liquid transfer operations (transfer, distribute, consolidate), along with Flex-specific features for resin tip handling and pressure-based liquid detection.
</about>

---

## src/opentrons/protocol_api/validation.py

<about>
This file (`validation.py`) is a validation module for the Opentrons Protocol API that provides comprehensive input validation and type checking functions for protocol parameters. It contains validation functions for ensuring correct pipette mounts, instrument mounts, deck slot locations, module models, labware definitions, axis maps, thermocycler parameters, and various numeric/boolean values. The module supports both OT-2 and Flex (OT-3) robot types and includes API version gating for features like coordinate deck labels (v2.15+), staging deck slots (v2.16+), lid stacks (v2.23+), and the Flex Stacker module (v2.23+). It validates all pipette types (1-channel, 8-channel, and 96-channel) and all module types including magnetic modules, temperature modules, thermocyclers, heater-shakers, magnetic blocks, absorbance readers, and flex stackers. The file also handles validation for disposal locations (trash bins and waste chutes), labware offsets, transfer parameters, and location types for liquid handling commands, ensuring type safety and proper error handling throughout the protocol API.
</about>

---

## src/opentrons/protocols/bundle.py

<about>
This file (`bundle.py`) is a utility module for handling zipped protocol bundles in the Opentrons system, not a protocol file itself. It provides functions to extract and create ZIP file bundles that contain Opentrons protocols and their associated resources. The module defines the structure of a protocol bundle, which must include a main protocol file (`protocol.ot2.py`) in the root directory, and can optionally contain labware definitions (JSON files in a `labware` directory), data files (in a `data` directory), and additional Python files. The `extract_bundle` function validates the bundle structure, extracts contents, and returns a `BundleContents` object, while the `create_bundle` function packages protocol contents into a properly formatted ZIP file. This is infrastructure code for protocol packaging and distribution rather than a protocol that controls robot operations.
</about>

---

## src/opentrons/protocols/**init**.py

<about>
This file is the `__init__.py` file for the `opentrons.protocols` module, which serves as the main entry point for protocol handling functionality in the Opentrons API. It provides a high-level abstraction layer that handles both v1 and v2 protocols, offering version-independent APIs for protocol simulation and execution, as well as version inference capabilities. This is not a protocol file itself, but rather infrastructure code that enables the processing of protocols regardless of their API version. The file does not specify any robot type, pipette configuration, modules, fixtures, adapters, labware, liquids, or protocol steps - it simply provides the framework for handling protocols that may contain such elements.
</about>

---

## src/opentrons/protocols/types.py

<about>
This file defines the core data types and structures used in the Opentrons protocol system, not a protocol itself. It establishes the fundamental classes and types for both JSON and Python protocols, including `JsonProtocol` and `PythonProtocol` dataclasses that inherit from `_ProtocolCommon`, which contains shared attributes like text content, filename, API version, and robot type (OT-2 or Flex). The file also defines metadata and requirements types for Python protocols, bundle contents for packaged protocols, and custom exceptions like `MalformedPythonProtocolError` and `ApiDeprecationError` for handling protocol validation errors. It includes important constants like error messages for missing run functions and deprecated API versions, with the minimum supported API version referenced from another module. This is infrastructure code that supports the protocol execution system rather than defining any specific liquid handling operations, pipette configurations, modules, or labware.
</about>

---

## src/opentrons/protocols/labware.py

<about>
This file (`src/opentrons/protocols/labware.py`) is a core module in the Opentrons API that handles labware definition management, including loading, saving, and validating labware definitions. It is not a protocol file but rather infrastructure code that provides functions to retrieve labware definitions from various sources (bundled definitions, custom definitions, or standard Opentrons definitions), validate labware definition JSON against schemas (versions 2 and 3), and save custom labware definitions to the file system. The module manages labware namespaces (distinguishing between 'opentrons' and custom namespaces), handles version control for labware definitions, and provides error handling for invalid labware files. Key functions include `get_labware_definition()` for retrieving definitions by load_name/namespace/version, `verify_definition()` for validating JSON labware definitions against schemas, `save_definition()` for persisting custom labware, and `get_all_labware_definitions()` for listing available labware. This module does not directly involve any specific robot type, pipettes, modules, fixtures, adapters, labware usage, liquids, or protocol steps - it's purely for labware definition management infrastructure.
</about>

---

## src/opentrons/protocols/parse.py

<about>
This file (`parse.py`) is a core module in the Opentrons API that handles parsing and validation of protocol files, supporting both Python (.py) and JSON (.json) protocol formats, as well as bundled protocols (.zip). It provides functionality to extract metadata, API version, robot type (OT-2 or Flex/OT-3), and other protocol requirements from protocol files, with support for API versions from 2.0 onwards (rejecting deprecated v1 protocols). The module includes validation for Python AST parsing, JSON schema validation (up to schema version 5), and special parsing modes to handle legacy protocols on robots. It extracts static information like metadata and requirements dictionaries from Python protocols, validates protocol structure (ensuring proper `run()` function definition), and handles bundled protocols containing additional labware definitions, data files, and Python modules. The file doesn't define specific pipettes, modules, fixtures, adapters, labware, liquids, or protocol steps - it's infrastructure code for parsing protocol files rather than a protocol itself.
</about>

---

## src/opentrons/protocol_api/core/well_grid.py

<about>
This file defines the `WellGrid` data structure and functionality for organizing labware wells into a grid format within the Opentrons API core. It provides a `WellGrid` dataclass that stores wells organized by both rows and columns, and includes a `create` function that takes a list of column-ordered wells and parses their names using regex to build dictionaries mapping row names to wells and column names to wells. This is not a protocol file but rather internal API infrastructure code that helps manage the spatial organization of wells in labware definitions. The code preserves historical behavior by organizing wells based on their names (e.g., "A1", "B2") rather than their position in the labware definition's ordering field.
</about>

---

## src/opentrons/protocol_api/core/protocol.py

<about>
This file defines the abstract interface (`AbstractProtocol`) for implementing protocol contexts in the Opentrons API, serving as a core abstraction layer that specifies all the methods required for protocol execution. It's not a protocol file itself but rather a foundational API component that supports both OT-2 and Flex robot types, defining methods for loading various pipette types (1-channel, 8-channel, 96-channel), modules, labware, adapters, and disposal locations (trash bins, waste chutes). The interface includes methods for robot control (movement, delays, comments, rail lights), liquid handling (defining liquids and liquid classes), and deck management (getting slot definitions, managing labware locations). While it doesn't implement specific protocol steps, it provides the abstract methods that concrete implementations must define to enable all protocol operations, including support for both standard and staging slots, lid handling, gripper operations, and liquid presence detection capabilities.
</about>

---

## src/opentrons/protocol_api/core/**init**.py

<about>
This file is the `__init__.py` module for the `opentrons.protocol_api.core` package, which serves as an internal implementation detail of the Python Protocol API. It provides facades to different protocol execution cores and interfaces for core protocol logic, including abstract protocols and labware offset providers. The file is not a protocol itself but rather infrastructure code, with most imports currently commented out due to import cycle issues. It defines the module's purpose as providing internal core functionality that should not be considered part of the public API, and includes placeholder imports for `AbstractProtocol`, `AbstractLabwareOffsetProvider`, `LabwareOffsetProvider`, `NullLabwareOffsetProvider`, and `ProvidedLabwareOffset` classes that will be exposed once import cycles are resolved.
</about>

---

## src/opentrons/protocol_api/core/labware.py

<about>
This file defines the abstract interface for labware in the Opentrons Protocol API, serving as a core component that other parts of the system must implement. It's not a protocol file but rather an abstract base class (`AbstractLabware`) that establishes the contract for how labware objects should behave in the API. The file defines methods for accessing labware properties (load name, URI, display name, definition, parameters), checking labware types (tip rack, adapter, lid, fixed trash), managing calibration offsets, handling tip tracking for tip racks, and loading liquids into wells. It uses generic typing to work with different well core implementations and includes helper classes like `LabwareLoadParams` for managing labware identification parameters. This interface ensures consistent behavior across different labware implementations in the Opentrons ecosystem, supporting both OT-2 and Flex robots through the abstract methods that concrete implementations must provide.
</about>

---

## src/opentrons/protocol_api/core/common.py

<about>
This file (`common.py`) is not a protocol but rather a core module that defines type aliases for the abstract interfaces used throughout the Opentrons Protocol API. It imports various abstract base classes from other core modules (instrument, labware, module, protocol, well, and robot) and creates concrete type aliases by parameterizing the generic abstract classes. The file establishes the core type system for protocol components including WellCore, LabwareCore, InstrumentCore, and various module cores (TemperatureModuleCore, MagneticModuleCore, ThermocyclerCore, HeaterShakerCore, MagneticBlockCore, AbsorbanceReaderCore, and FlexStackerCore), as well as RobotCore and ProtocolCore. This type aliasing system helps maintain consistency and type safety across the API by defining how different protocol components relate to each other through their generic type parameters.
</about>

---

## src/opentrons/protocol_api/core/core_map.py

<about>
This file (`core_map.py`) is not a protocol but rather a core infrastructure component of the Opentrons API that manages the mapping between internal core objects and public API objects. The `LoadedCoreMap` class maintains a bidirectional relationship between equipment cores (LabwareCore and ModuleCore instances) and their corresponding public PAPI (Protocol API) objects (Labware and ModuleTypes). This mapping system allows the API to track and retrieve public objects from their internal core representations, managing the circular dependencies that arise from this architecture. The file uses type hints and overloaded methods to ensure type safety when adding and retrieving labware and module mappings, with a `get_or_add` method that can lazily create and register new labware contexts when needed.
</about>

---

## src/opentrons/protocol_api/core/robot.py

<about>
This file defines an abstract base class (`AbstractRobot`) that serves as the core interface for robot control in the Opentrons Protocol API. It establishes the contract for robot implementations by declaring abstract methods for essential robot operations including: retrieving pipette information from the engine, calculating plunger positions based on volume or named positions, moving the robot mount to specific coordinates or along axes (both absolute and relative movements), and controlling the gripper (release and close operations). This is not a protocol file but rather a foundational API component that would be implemented by concrete robot classes for both OT-2 and Flex robots, providing a unified interface for pipette control, movement operations, and gripper functionality regardless of the specific robot model being used.
</about>

---

## src/opentrons/protocol_api/core/module.py

<about>
This file defines the core module control interfaces for the Opentrons Protocol API, providing abstract base classes for all hardware modules that can be attached to Opentrons robots. It's not a protocol file but rather the foundational API layer that defines how different module types (Temperature Module, Magnetic Module, Thermocycler, Heater-Shaker, Magnetic Block, Absorbance Reader, and Flex Stacker) should be controlled programmatically. The file establishes abstract methods for common operations like getting serial numbers, controlling temperatures, engaging magnets, opening/closing lids, shaking, reading absorbance values, and managing labware storage in the Flex Stacker. Each module type has its own abstract class with specific control methods relevant to that module's functionality. This architecture supports both OT-2 and Flex robots, though some modules like the Absorbance Reader and Flex Stacker are Flex-specific. The file uses Python's ABC (Abstract Base Class) pattern and generics to ensure type safety and consistent interfaces across all module implementations.
</about>

---

## src/opentrons/protocol_api/core/instrument.py

<about>
This file defines the abstract interface for instrument (pipette) operations in the Opentrons Protocol API, serving as the core contract that all instrument implementations must follow. It's not a protocol file but rather an abstract base class that specifies all the methods required for pipette control, including basic liquid handling operations (aspirate, dispense, blow_out, air_gap), tip management (pick_up_tip, drop_tip), movement control, configuration methods (nozzle layout, flow rates), and advanced features like liquid detection and liquid class-based transfers. The interface is generic and supports all pipette types (1-channel, 8-channel, 96-channel) on both OT-2 and Flex robots, with methods for handling various disposal locations (TrashBin, WasteChute), well interactions, and pipette state management. While it doesn't specify particular labware, modules, or liquids, it provides the foundational structure for all instrument operations including volume tracking, tip state management, flow rate control, and specialized methods for resin tips and liquid presence detection.
</about>

---

## src/opentrons/protocol_api/core/well.py

<about>
This file defines the abstract interface for Well core implementations in the Opentrons Protocol API. It's not a protocol file but rather a core API component that establishes the contract for well-related functionality across different implementations. The `AbstractWellCore` class defines abstract methods for accessing well properties (diameter, length, width, depth), managing tip presence, retrieving well identification information (display name, well name, column/row names), calculating positions within wells (top, bottom, center, meniscus), handling liquid operations (loading liquid, tracking liquid height and volume), and performing geometric calculations (from_center_cartesian, height_from_volume, volume_from_height). This abstract base class ensures consistent well behavior across different protocol engine implementations and provides type safety through the `WellCoreType` TypeVar. The file doesn't specify robot types, pipettes, modules, fixtures, adapters, labware, liquids, or protocol steps as it's a foundational API component rather than a user-facing protocol.
</about>

---

## src/opentrons/protocols/api_support/deck_type.py

<about>
This file is part of the Opentrons API support infrastructure that handles deck type determination and fixed trash loading logic for different protocol versions and robot types. It defines constants for different deck types (OT-2 standard, OT-2 short trash, and OT-3 standard), provides functions to determine whether fixed trash labware should be automatically loaded based on API version (with a cutoff at version 2.15 for Python protocols and schema version 7 for JSON protocols), and includes logic to select the appropriate deck type based on robot type and configuration. The file supports both OT-2 and Flex (OT-3) robots, with special handling for OT-2's short trash deck variant, and includes error handling for cases where protocols attempt to access trash bins that haven't been loaded. This is not a protocol file but rather a utility module that helps the API manage deck configurations across different protocol versions and robot types.
</about>

---

## src/opentrons/protocols/api_support/definitions.py

<about>
This file defines API version constants for the Opentrons protocol API, not a protocol file. It establishes the maximum supported API version (2.24), minimum supported version (2.0) across all robot types, and the minimum supported version specifically for the Flex robot (2.15). The file explains that Flex requires at least version 2.15 due to infrastructural requirements and because versions before 2.14 use a legacy backend that only supports OT-2 robots. This is a configuration/definition file that helps manage API version compatibility across different Opentrons robot platforms.
</about>

---

## src/opentrons/protocols/api_support/labware_like.py

<about>
This file defines a wrapper class `LabwareLike` that provides a unified interface for handling various labware-related objects in the Opentrons API. It's not a protocol file but rather a support module that enables the API to treat different types of objects (Labware, Well, slot strings, ModuleGeometry, ModuleContext, and OffDeckType) uniformly through a common interface. The class provides methods to identify the type of wrapped object, access parent relationships, convert between types, and extract properties like quirks (special behaviors) from the labware hierarchy. Key features include checking if an object is a well, labware, slot, or module; traversing parent relationships; extracting quirks like "fixedTrash" or "centerMultichannelOnWells"; and finding the topmost parent slot or module parent in the labware tree. This abstraction layer is crucial for the Location system in the API, allowing consistent handling of different location types throughout the protocol execution system.
</about>

---

## src/opentrons/protocols/api_support/util.py

<about>
This file is a utility module for the Opentrons Protocol API that provides helper functions, classes, and decorators for protocol development. It includes custom exception classes for robot type and API version errors, utility classes for managing flow rates (`FlowRates`), plunger speeds (`PlungerSpeeds`), and axis maximum speeds (`AxisMaxSpeeds`), as well as helper functions for edge path determination during touch-tip operations, labware column shifting, and API version checking. The file also contains the `requires_version` decorator that enforces API version requirements for protocol methods and attributes, and various utility functions for value validation and clamping. This is not a protocol file but rather infrastructure code that supports protocol execution across both OT-2 and Flex (OT-3) robots, handling compatibility between different API versions and robot types.
</about>

---

## src/opentrons/protocols/api_support/constants.py

<about>
This file defines constants used throughout the Opentrons API for protocol support. It establishes namespace constants for distinguishing between official Opentrons labware definitions ("opentrons") and custom user-defined labware ("custom_beta"), and defines file paths for accessing labware definitions - both the standard definitions that ship with the software and user-defined custom labware stored in the user's configuration directory. This is not a protocol file but rather a configuration constants module that supports the API's labware management system.
</about>

---

## src/opentrons/protocols/api_support/**init**.py

<about>
This file (`__init__.py`) appears to be an empty initialization file for the `api_support` module within the Opentrons protocols package. As an empty `__init__.py` file, it serves to make the `api_support` directory a Python package, allowing other modules to import from it. This is not a protocol file but rather a structural component of the Opentrons API library. Since the file contains no actual code or documentation, none of the requested details about protocol type, API level, robot type, pipettes, modules, fixtures, adapters, labware, liquids, or protocol steps apply to this file.
</about>

---

## src/opentrons/protocols/api_support/types.py

<about>
This file defines type definitions and data structures used in the Opentrons API, not a protocol file. It contains two main components: an `APIVersion` class that represents and parses API version numbers (e.g., "2.14" into major and minor components), and thermocycler-related TypedDict definitions (`ThermocyclerStepBase` and `ThermocyclerStep`) that define the structure for thermocycler step parameters including required temperature and optional hold time specifications in seconds or minutes. This is a support file that provides type safety and data structures for other parts of the Opentrons API rather than implementing any protocol logic or robot control functionality.
</about>

---

## src/opentrons/protocols/api_support/instrument.py

<about>
This file is not a protocol but rather a support module for the Opentrons API that provides validation and utility functions for instrument operations. It contains helper functions for validating blowout locations based on API version and liquid handling commands, calculating tip lengths for pipettes, validating tip rack compatibility with pipettes, and ensuring locations are valid for liquid handling operations. The module supports both OT-2 and Flex (OT-3) robots and includes validation logic for different pipette types (p10, p20, p50, p200, p300, p1000 for OT-2, and p50, p200, p1000 for Flex) with their compatible tip rack volumes. It handles 1-channel, 8-channel, and 96-channel pipettes through the validation functions. The file doesn't implement specific protocol steps but provides the underlying validation infrastructure used by the API when executing liquid handling commands like aspirate, dispense, and blowout operations.
</about>

---

## src/opentrons/protocols/api_support/tip_tracker.py

<about>
This file implements the TipTracker class, which is part of the Opentrons API's internal support system for managing tip usage in labware during protocol execution. The TipTracker monitors which tips have been used or are available in tip racks, providing methods to find the next available tip (`next_tip`), mark tips as used when picked up (`use_tips`), find previously used tip locations (`previous_tip`), and return tips to the tracker when dropped back (`return_tips`). This is not a protocol file but rather a utility class that supports the API's tip tracking functionality. The class works with well columns and can handle both single-channel operations (num_channels=1) and multi-channel operations (num_channels=8), automatically determining which tips are affected based on the starting well and pipette geometry. No specific robot type, modules, fixtures, adapters, labware, or liquids are mentioned as this is infrastructure code that works generically with any tip-containing labware.
</about>

---

## src/opentrons/protocols/execution/dev_types.py

<about>
This file defines type definitions and protocols for the Opentrons protocol execution system, specifically for static type checking during development. It's not a protocol file but rather a type definition module that provides TypedDict definitions for various protocol command dispatchers. The file includes type definitions for pipette operations (like aspirate, dispense, blowout, pickUpTip, dropTip, touchTip, moveToSlot, moveToWell, and airGap) and module-specific operations for the Magnetic Module (engage/disengage magnet), Temperature Module (set temperature, deactivate, await temperature), and Thermocycler Module (lid operations, temperature control, profile running). These type definitions are used to ensure type safety when implementing protocol execution handlers for both OT-2 and Flex robots, supporting all pipette types (1-channel, 8-channel, 96-channel) through the generic dispatch system. The file explicitly notes that it contains types requiring development dependencies and should only be used for static type checking, not runtime execution.
</about>

---

## src/opentrons/protocols/execution/execute_python.py

<about>
This file implements the Python protocol execution engine for Opentrons robots, handling the execution of user-written Python protocols. It provides functions to validate and execute both the `add_parameters` function (for protocol parameterization) and the main `run` function that contains protocol logic. The file includes error handling mechanisms that parse exceptions and present them with meaningful context, including line numbers from the original protocol file. It supports protocol parameters with runtime overrides (including CSV file parameters) and integrates with the ProtocolContext API. This is not a protocol file itself but rather core infrastructure code that executes Python protocols on both OT-2 and Flex robots, handling various error conditions including SmoothieAlarm errors and execution cancellations.
</about>

---

## src/opentrons/protocols/execution/execute_json_v3.py

<about>
This file (`execute_json_v3.py`) is not a protocol but rather an execution engine for JSON-based protocols in the Opentrons system. It provides functionality to parse and execute JSON protocol version 3 commands by translating them into Python API calls. The file contains helper functions to load pipettes and labware from JSON definitions, and a dispatcher system that maps JSON command types (like aspirate, dispense, blowout, pickUpTip, dropTip, touchTip, moveToSlot, and delay) to their corresponding Python implementation functions. It handles both pipette-specific commands and robot-level commands, managing parameters like flow rates, offsets, and well locations. The code supports any pipette type (1-channel, 8-channel, or 96-channel) and robot type (OT-2 or Flex) that the JSON protocol specifies, but doesn't directly reference specific modules, fixtures, adapters, labware, or liquids - these would be defined in the JSON protocol being executed.
</about>

---

## src/opentrons/protocols/execution/json_dispatchers.py

<about>
This file is not a protocol but rather a dispatcher module that maps JSON protocol commands to their corresponding execution functions in the Opentrons API. It serves as a command routing system that connects JSON-formatted protocol commands (from versions 3, 4, and 5) to their implementation functions. The file defines dispatch dictionaries for different command types: pipette commands (including blowout, pick up tip, drop tip, aspirate, dispense, touch tip, air gap, and move to well), magnetic module commands (engage/disengage magnet), temperature module commands (set temperature, deactivate, await temperature), and thermocycler module commands (open/close lid, set block/lid temperature, run profile, deactivate block/lid). The dispatcher supports both OT-2 and Flex robots and handles commands for all pipette types (1-channel, 8-channel, 96-channel), though specific pipette types aren't explicitly mentioned in this file. The modules referenced are the Magnetic Module, Temperature Module, and Thermocycler Module, with no specific fixtures, adapters, labware, or liquids mentioned as this is infrastructure code rather than a protocol implementation.
</about>

---

## src/opentrons/protocols/execution/execute.py

<about>
This file is the core execution module for running Opentrons protocols, not a protocol itself. It serves as the main entry point that determines how to execute different protocol types (Python or JSON) based on their API version or schema. The module handles Python protocols with API version 2.0 and above, executing them through the `exec_run` function, and manages cleanup of CSV parameters for API version 2.18+. For JSON protocols, it supports schema versions 3, 4, and 5, loading pipettes, labware, and modules as needed, then dispatching commands through appropriate command maps for different module types (temperature, magnetic, and thermocycler modules). The file doesn't specify robot type, pipette configurations, specific labware, liquids, or protocol steps - instead, it provides the infrastructure to execute protocols that contain these elements.
</about>

---

## src/opentrons/protocols/execution/**init**.py

<about>
This file is an empty Python `__init__.py` file located in the `opentrons/protocols/execution` module, serving as a package initializer. It is not a protocol file but rather a structural component of the Opentrons API codebase that allows the `execution` directory to be recognized as a Python package. Since the file is empty, it doesn't contain any protocol information, API level specifications, robot type references, pipette configurations, modules, fixtures, adapters, labware, liquids, or protocol steps. Its sole purpose is to enable Python to treat the `execution` directory as an importable package within the Opentrons protocols module hierarchy.
</about>

---

## src/opentrons/protocols/execution/types.py

<about>
This file defines type aliases for the Opentrons protocol execution system, not a protocol file. It contains two simple type definitions: `Instruments` as a dictionary mapping string keys to `InstrumentContext` objects (representing pipettes), and `LoadedLabware` as a dictionary mapping string keys to `Labware` objects (representing labware items). These type aliases are used throughout the Opentrons API to provide type hints for collections of instruments and labware during protocol execution. The file doesn't contain any protocol implementation, API level specifications, robot type requirements, or specific pipette/module/labware configurations - it's purely a type definition file for the internal API structure.
</about>

---

## src/opentrons/protocols/execution/execute_json_v5.py

<about>
This file (`execute_json_v5.py`) is part of the Opentrons protocol execution engine, specifically handling JSON protocol execution for API version 5. It contains a single function `_move_to_well()` that implements pipette movement to a specific well location with optional offsets. This is not a protocol file but rather internal API implementation code that processes movement commands from JSON-based protocols. The function takes instrument and labware information along with movement parameters, retrieves the appropriate pipette and well, applies any specified x/y/z offsets, and moves the pipette to the calculated position relative to the well bottom. It supports optional parameters for forced direct movement and minimum Z height constraints. The file imports functionality from the v3 execution module, indicating it builds upon previous API versions while adding v5-specific movement capabilities.
</about>

---

## src/opentrons/protocols/execution/execute_json_v4.py

<about>
This file is part of the Opentrons protocol execution engine that handles JSON protocol format versions 4 and 5. It provides high-level functions for loading labware and modules from JSON definitions, and dispatching commands to execute protocols. The file supports both OT-2 and Flex robots (as it references both in the context of different module types), and while it doesn't directly specify pipette types, it handles pipette commands through a dispatch system. The code supports three types of modules: Magnetic Module, Temperature Module, and Thermocycler Module, with specific command handlers for each module's operations (engage/disengage magnets, set temperatures, run profiles, etc.). The file includes validation functions to ensure thermocycler commands follow proper async behavior patterns and don't use unimplemented parameters. Key protocol steps handled include module operations (temperature control, magnetic engagement, thermocycler lid operations), pipette movements, delays, and movement to specific deck slots. The special handling of the thermocycler's spanning slot ("span7_8_10_11") indicates support for the thermocycler's unique positioning requirements.
</about>

---

## src/opentrons/protocols/execution/errors.py

<about>
This file defines custom error handling for protocol execution in the Opentrons API, not a protocol file. It contains the `ExceptionInProtocolError` class which wraps exceptions raised during protocol execution, providing proper error message formatting for the RPC system. The class captures the original exception, traceback, error message, and line number where the error occurred, formatting them into a standardized message structure. This is part of the internal error handling infrastructure that helps provide clear, informative error messages to users when their protocols encounter runtime errors, including the specific line number in the protocol where the error occurred.
</about>

---

## src/opentrons/protocols/parameters/csv_parameter_interface.py

<about>
This file defines the `CSVParameter` class, which is part of the Opentrons protocol parameters system and provides an interface for handling CSV files as runtime parameters in protocols. The class manages CSV file contents passed as bytes, offering methods to access the file as a text handler, retrieve its contents as a UTF-8 string, and parse the CSV data into a list of lists with automatic dialect detection and trailing empty row removal. This is not a protocol file but rather a utility class that supports protocol execution by allowing users to pass CSV files as parameters to their protocols, with error handling for cases where the CSV parameter is required but not provided. The class is designed to work with different API versions and includes functionality to handle temporary file creation for read-only access to the CSV data.
</about>

---

## src/opentrons/protocols/parameters/csv_parameter_definition.py

<about>
This file defines the `CSVParameterDefinition` class, which is part of the Opentrons protocol parameters system for handling CSV file inputs in protocols. It's not a protocol file itself, but rather infrastructure code that allows protocol authors to define CSV file parameters that users can provide when running protocols. The class manages CSV file data as bytes, includes validation for display names and variable names, and provides methods to convert the parameter definition into different formats needed by the Opentrons system - both for the protocol API interface (`CSVParameter`) and for the Protocol Engine runtime (`CSVParameter` type). The file also includes a factory function `create_csv_parameter` for convenient parameter creation. This is API infrastructure code that supports both OT-2 and Flex robots, but doesn't directly involve pipettes, modules, labware, or protocol steps.
</about>

---

## src/opentrons/protocols/parameters/**init**.py

<about>
This file is an empty Python `__init__.py` file located in the `opentrons/protocols/parameters` module, serving as a package initializer. It is not a protocol file but rather a structural component of the Opentrons API codebase that allows the `parameters` directory to be recognized as a Python package. Since the file is empty, it doesn't contain any protocol information, API level specifications, robot types, pipettes, modules, fixtures, adapters, labware, liquids, or protocol steps. Its sole purpose is to enable Python to treat the `parameters` directory as an importable module within the Opentrons protocols package structure.
</about>

---

## src/opentrons/protocols/parameters/types.py

<about>
This file defines type definitions and interfaces for protocol parameters in the Opentrons API, not a protocol file. It establishes the type system for parameter values that can be used in protocols, including primitive types (string, int, float, bool), CSV parameters, and a ParameterChoice TypedDict for creating parameter options with display names and values. The file uses Python's typing module to create type aliases and constraints for parameter handling, with `PrimitiveAllowedTypes` for basic parameter values, `AllAllowedTypes` including bytes and None, `UserFacingTypes` for parameters exposed to users including CSV parameters, and a generic `ParamType` TypeVar bounded by all allowed types. This is infrastructure code that supports the parameter system in Opentrons protocols rather than being a protocol itself.
</about>

---

## src/opentrons/protocols/parameters/parameter_definition.py

<about>
This file defines the parameter system for Opentrons protocols, providing a framework for creating user-defined parameters that can be configured at runtime. It contains the `ParameterDefinition` class and helper functions for creating integer, float, boolean, and string parameters with validation, constraints, and conversion to Protocol Engine types. The file is not a protocol itself but rather infrastructure code that enables protocol authors to define configurable parameters with display names, variable names, default values, ranges (min/max), choices, descriptions, and units. It includes validation logic to ensure parameter values meet specified constraints and provides methods to convert parameters to Protocol Engine format for client communication. The code supports primitive types (int, float, str, bool) and handles both range-based constraints and enumerated choices for parameter values.
</about>

---

## src/opentrons/protocols/parameters/exceptions.py

<about>
This file defines custom exception classes for the Opentrons protocol parameters system. It contains five exception classes that handle various parameter-related errors: `RuntimeParameterRequired` (raised when a parameter must be set for full analysis), `ParameterValueError` (for invalid parameter values), `ParameterDefinitionError` (for invalid parameter definitions), `ParameterNameError` (for invalid parameter names or descriptions), and `IncompatibleParameterError` (for conflicting parameters). This is not a protocol file but rather a Python module that provides error handling infrastructure for the Opentrons API's parameter validation system. The file uses the Opentrons shared data error framework and extends standard Python exceptions like `ValueError` and `GeneralError`.
</about>

---

## src/opentrons/protocols/parameters/validation.py

<about>
This file is a validation module for the Opentrons protocol parameters system, not a protocol file. It contains functions for validating parameter definitions and values used in Opentrons protocols, including validation of variable names (ensuring they're valid Python identifiers and unique), display names and descriptions (checking character limits), units, parameter types (int, float, str, bool), and parameter constraints (minimum/maximum values and choice lists). The module enforces various rules such as maximum character lengths (10 for units, 30 for display names, 100 for descriptions), type conversions between compatible types (e.g., float to int when appropriate), and ensures that parameters have either choices defined or min/max constraints but not both. This is infrastructure code that supports the parameter system in Opentrons protocols rather than being a protocol itself.
</about>

---

## src/opentrons/protocols/advanced_control/**init**.py

<about>
This file is an empty Python `__init__.py` file located in the `opentrons/protocols/advanced_control` directory, serving as a package initializer for the advanced control module within the Opentrons protocols system. As an empty initialization file, it contains no actual code, protocol definitions, or documentation - it simply marks the directory as a Python package. Since this is not a protocol file but rather a structural component of the package hierarchy, none of the protocol-specific details (API level, robot type, pipettes, modules, fixtures, adapters, labware, liquids, or protocol steps) apply to this file.
</about>

---

## src/opentrons/protocols/advanced_control/common.py

<about>
This file defines common data structures and enumerations used for advanced control functions in the Opentrons API, not a protocol file. It contains a `MixStrategy` enum with options for mixing timing (BOTH, BEFORE, AFTER, NEVER), a `MixOpts` NamedTuple for customizing mix behavior with parameters for repetitions, volume, and rate, and a `Mix` NamedTuple that combines mix options for before and after operations. The file serves as a foundational module providing shared types and configurations for more complex liquid handling operations in the Opentrons system, but doesn't contain any actual protocol implementation, robot-specific code, or references to pipettes, modules, labware, or protocol steps.
</about>

---

## src/opentrons/protocols/advanced_control/mix.py

<about>
This file (`mix.py`) is a utility module in the Opentrons advanced control API that handles mix strategy determination from keyword arguments. It contains a single function `mix_from_kwargs` that parses keyword arguments (specifically `mix_before` and `mix_after`) from transfer operations to determine the appropriate mixing strategy (NEVER, BEFORE, AFTER, or BOTH) and creates corresponding Mix configuration objects with repetitions and volume parameters. This is not a protocol file but rather an internal API component that supports the mixing functionality in liquid handling operations. The file doesn't directly reference specific robot types, pipettes, modules, fixtures, adapters, labware, or liquids - it's a helper function that processes mixing parameters for use by other parts of the API.
</about>

---

## src/opentrons/protocols/duration/**init**.py

<about>
This file is a Python package initialization file (`__init__.py`) for the duration module within the Opentrons protocols package. It simply imports and exports the `DurationEstimator` class, making it available when the duration module is imported. This is not a protocol file but rather part of the Opentrons API infrastructure that likely provides functionality for estimating protocol execution duration. The file contains no protocol-specific information, pipette configurations, modules, fixtures, adapters, labware, liquids, or protocol steps - it's purely a module organization file that exposes the DurationEstimator class for use by other parts of the Opentrons system.
</about>

---

## src/opentrons/protocols/duration/errors.py

<about>
This file defines a custom exception class `DurationEstimatorException` for the Opentrons protocol duration estimation system. It's a simple error handling module that creates a specialized exception to be raised when errors occur during protocol duration estimation, wrapping error messages with a standardized format. This is not a protocol file but rather an internal API component for error handling. N/A for all protocol-specific questions (API level, robot type, pipettes, modules, fixtures, adapters, labware, liquids, and protocol steps) as this is purely an exception class definition.
</about>

---

## src/opentrons/protocols/duration/estimator.py

<about>
This file implements a DurationEstimator class that calculates the estimated runtime duration for Opentrons protocols by analyzing protocol commands and their execution times. It's not a protocol file but rather a core component of the Opentrons API that listens to protocol messages and estimates how long each command will take based on factors like deck movement, pipetting speeds, temperature changes, and module operations. The estimator handles various command types including pick up tip, drop tip, aspirate, dispense, blow out, touch tip, delays, and module-specific operations for Temperature Module and Thermocycler Module. It calculates durations by considering gantry movement speeds, z-axis travel times, flow rates, and temperature change rates based on empirical data. The class maintains state information about the last deck slot accessed and module temperatures to accurately estimate inter-command travel times and temperature ramping durations. This tool is useful for providing users with protocol runtime estimates before execution.
</about>

---

## src/opentrons/protocols/api_support/**pycache**/constants.cpython-312.pyc

Error: Could not analyze file - 'utf-8' codec can't decode byte 0xcb in position 0: invalid continuation byte

---

## src/opentrons/protocols/api_support/**pycache**/util.cpython-312.pyc

Error: Could not analyze file - 'utf-8' codec can't decode byte 0xcb in position 0: invalid continuation byte

---

## src/opentrons/protocols/api_support/**pycache**/labware_like.cpython-312.pyc

Error: Could not analyze file - 'utf-8' codec can't decode byte 0xcb in position 0: invalid continuation byte

---

## src/opentrons/protocols/api_support/**pycache**/types.cpython-312.pyc

Error: Could not analyze file - 'utf-8' codec can't decode byte 0xcb in position 0: invalid continuation byte

---

## src/opentrons/protocols/api_support/**pycache**/**init**.cpython-312.pyc

Error: Could not analyze file - 'utf-8' codec can't decode byte 0xcb in position 0: invalid continuation byte

---

## src/opentrons/protocols/api_support/**pycache**/definitions.cpython-312.pyc

Error: Could not analyze file - 'utf-8' codec can't decode byte 0xcb in position 0: invalid continuation byte

---

## src/opentrons/protocols/advanced_control/transfers/**init**.py

<about>
This file is an empty Python `__init__.py` file located in the transfers module of the Opentrons advanced control protocols package. As an empty initialization file, it serves to mark the `transfers` directory as a Python package, allowing other modules to import from this namespace. This is not a protocol file but rather a structural component of the Opentrons API library. Since the file contains no code, there are no specific protocol types, API levels, robot types, pipettes, modules, fixtures, adapters, labware, liquids, or protocol steps to describe.
</about>

---

## src/opentrons/protocols/advanced_control/transfers/transfer_liquid_utils.py

<about>
This file contains utility functions for the Opentrons liquid transfer operations (transfer_liquid, consolidate_liquid, and distribute_liquid), not a protocol file. It provides two main functions: `raise_if_location_inside_liquid` which validates that pipetting locations are not inside the liquid during submerge/retract operations, and `group_wells_for_multi_channel_transfer` which optimizes well targeting for multi-channel pipettes by grouping wells based on the pipette's nozzle configuration. The code supports 8-channel column configurations, 12-channel row configurations, and full 96-channel pipettes, specifically handling 96-well and 384-well plate formats. While not a protocol itself, these utilities are designed to work with both OT-2 and Flex robots (as evidenced by the liquid height detection features which are Flex-specific), and the multi-channel grouping logic indicates support for various pipette configurations including 8-tip, 12-tip, and 96-tip arrangements.
</about>

---

## src/opentrons/protocols/advanced_control/transfers/transfer.py

<about>
This file is not a protocol but rather a core component of the Opentrons API's advanced liquid handling system that implements the logic for complex transfer operations (transfer, distribute, consolidate). It defines the `TransferPlan` class which calculates and manages state for M:N transfers between sources and destinations, handling various transfer strategies including tip management (new tip policies: ONCE, ALWAYS, NEVER), air gaps, carryover volumes, mixing strategies (BEFORE, AFTER, BOTH, NEVER), blow out strategies (TRASH, SOURCE, DEST, CUSTOM_LOCATION), and touch tip options. The file supports both OT-2 and Flex robots with special handling for multi-channel pipettes (8-channel and 96-channel) and partial tip configurations (API version 2.18+), though it doesn't specify particular labware, modules, or liquids. The implementation includes three main transfer modes - TRANSFER (multiple sources to multiple destinations), DISTRIBUTE (one source to many destinations), and CONSOLIDATE (many sources to one destination) - each with its own sequencing logic for aspirate/dispense actions and associated options.
</about>

---

## src/opentrons/protocols/advanced_control/transfers/common.py

<about>
This file is not a protocol but rather a common utility module for the Opentrons API's advanced transfer control system. It contains shared functions and classes used by both v1 transfers and liquid-class-based transfers, including error handling classes (NoLiquidClassPropertyError), transfer tip policy enumerations (TransferTipPolicyV2 with options like "once", "always", "per source", "never", "per destination"), and volume constraint validation functions. The module provides critical functions for checking valid volume parameters to ensure air gaps, disposal volumes, and aspirate volumes don't exceed pipette capacity, and includes sophisticated volume-splitting algorithms (expand_for_volume_constraints and expand_for_volume_constraints_for_liquid_classes) that automatically divide large volume transfers into smaller, manageable chunks that fit within pipette constraints while accounting for air gaps, disposal volumes, and conditioning volumes. This is infrastructure code that supports the transfer functionality across different robot types (OT2 and Flex) and pipette configurations, but doesn't specify particular pipettes, modules, labware, or protocol steps itself.
</about>

---

## tests/opentrons/protocol_api/test_robot_context.py

<about>
This file contains unit tests for the `RobotContext` class in the Opentrons Protocol API, testing various robot movement and control functionalities. It's a test file, not a protocol, that uses pytest and the Decoy mocking framework to verify the behavior of robot context methods including `move_to`, `move_axes_to`, `move_axes_relative`, `axis_coordinates_for`, and plunger coordinate calculations. The tests cover both OT-3 Standard robot functionality with P1000_SINGLE_FLEX pipettes on both left and right mounts, though these are mocked for testing purposes. The file tests various coordinate systems and axis types (X, Y, Z_G, Z_L, P_L, P_R), mount specifications (left, right, extension), and plunger position calculations for different actions (aspirate, dispense) and positions (top, bottom). No actual modules, fixtures, adapters, labware, or liquids are used as this is purely a unit test file that mocks all dependencies to test the RobotContext class methods in isolation.
</about>

---

## tests/opentrons/protocol_api/test_liquid_class.py

<about>
This file contains unit tests for the LiquidClass functionality in the Opentrons Protocol API, specifically testing the creation, retrieval, and updating of liquid class properties for different pipette and tip combinations. It's a test file, not a protocol, that validates the LiquidClass methods including creating liquid classes from definitions, getting properties for specific pipette-tip combinations (using both string identifiers and mock objects), handling errors for non-existent pipette-tip combinations, creating liquid classes from transfer properties, and updating liquid class properties. The tests reference Flex pipettes (specifically "flex_1channel_50") and tip racks ("opentrons_flex_96_tiprack_50ul") in the test cases, but these are used as test data rather than actual protocol implementation. No modules, fixtures, adapters, or specific liquids are mentioned, and there are no protocol steps as this is a testing file that validates the API's liquid class management functionality.
</about>

---

## tests/opentrons/protocol_api/test_heater_shaker_context.py

<about>
This file is a test suite for the HeaterShakerContext class in the Opentrons Protocol API, not a protocol file. It uses pytest and the Decoy mocking framework to test various methods of the HeaterShakerContext, including temperature control (get/set current and target temperature, wait for temperature), speed control (get/set current and target speed for shaking), labware latch operations (open/close), and status queries (temperature status, speed status, latch status). The tests verify that the HeaterShakerContext properly delegates calls to its underlying HeaterShakerCore implementation and publishes appropriate command messages through the LegacyBroker. The file tests functionality for the Heater-Shaker module, which is compatible with both OT-2 and Flex robots, though no specific robot type, pipettes, labware, liquids, or protocol steps are mentioned as this is a unit test file rather than an actual protocol.
</about>

---

## tests/opentrons/protocol_api/test_lc_blowout_properties.py

<about>
This file contains unit tests for the liquid class blowout properties in the Opentrons protocol API, specifically testing the `_build_blowout_properties` function and the `BlowoutProperties` class. It's a test file, not a protocol, that uses property-based testing with Hypothesis to validate various aspects of blowout configuration including enable/disable functionality, flow rate validation (accepting positive non-zero values and rejecting invalid/negative values), and location validation (accepting valid locations like "destination", "trash", "source" and rejecting invalid ones). The tests ensure proper validation of blowout parameters and error handling for invalid inputs, testing both instantiation and property setter behaviors. No specific robot type, pipettes, modules, fixtures, adapters, labware, liquids, or protocol steps are mentioned as this is purely a testing file for API validation logic.
</about>

---

## tests/opentrons/protocol_api/test_deck.py

<about>
This file contains unit tests for the `Deck` class in the Opentrons Protocol API, testing various deck-related functionality including slot access, item retrieval/deletion, position calculations, and deck properties. It's not a protocol file but rather a test suite that uses pytest and the Decoy mocking framework to verify the behavior of deck operations. The tests cover both OT-2 and OT-3 (Flex) robot types, with specific tests for slot validation, labware movement, module handling, and API version compatibility (particularly testing restrictions in API version 2.14). The file tests core deck functionality like getting/setting items in deck slots, calculating positions, finding adjacent slots, and accessing calibration points, but doesn't involve actual pipettes, modules, fixtures, adapters, or liquid handling operations.
</about>

---

## tests/opentrons/protocol_api/test_instrument_context.py

<about>
This file contains comprehensive unit tests for the InstrumentContext class in the Opentrons Protocol API, testing the public interface methods for pipette operations. It's a test file, not a protocol, that validates functionality across different API versions (from 2.0 to MAX_SUPPORTED_VERSION) and robot types (OT-2 and Flex/OT-3). The tests cover both single and multi-channel pipettes (1, 8, and 96 channels) and verify core liquid handling operations including aspirate, dispense, pick_up_tip, drop_tip, blow_out, touch_tip, mix, air_gap, and advanced features like liquid presence detection, nozzle configuration, and the new liquid class-based transfer methods (transfer_with_liquid_class, distribute_with_liquid_class, consolidate_with_liquid_class). The file uses mock objects for various components including wells, labware, trash bins, and waste chutes, and tests different disposal locations and tip handling policies. No specific modules, fixtures, adapters, or liquids are mentioned as this is testing the API interface rather than implementing an actual protocol.
</about>

---

## tests/opentrons/protocol_api/test_validation.py

<about>
This file contains comprehensive unit tests for the Protocol API input validation module in Opentrons, testing various validation functions that ensure proper input types and values for protocol operations. The tests cover validation for mount positions (left/right), pipette names (including all OT-2 and Flex pipette types like P10_SINGLE through P1000_96), deck slot conversions (supporting both numeric and coordinate-based naming), module models (MagneticModule, TemperatureModule, ThermocyclerModule, HeaterShakerModule), and various parameter validations for floats, booleans, coordinates, and axis maps. The file tests both OT-2 and Flex (OT-3) robot types, with specific tests for 96-channel pipette mount handling and staging slot validation. While it doesn't test actual protocol execution, it validates inputs for various protocol operations including location validation for wells, trash bins, and waste chutes, thermocycler profile steps, labware offset vectors, and transfer tip policies. The tests use pytest parametrization extensively to cover multiple input scenarios and edge cases, ensuring robust validation of user inputs before they reach the actual protocol execution layer.
</about>

---

## tests/opentrons/protocol_api/test_lc_mix_properties.py

<about>
This file contains unit tests for the mix properties functionality in the Opentrons protocol API, specifically testing the `_build_mix_properties` function and the `MixProperties` class. It's a test file, not a protocol, that validates various aspects of mix properties including enabling/disabling mixing, handling None values, and validating volume and repetition parameters. The tests use property-based testing with Hypothesis to ensure that mix properties correctly accept valid values (positive non-zero floats/ints for volume, non-negative integers for repetitions) and reject invalid inputs. The file tests the validation logic for boolean enable/disable flags, volume parameters that must be greater than zero, and repetition counts that must be non-negative integers. No specific robot type, pipettes, modules, fixtures, adapters, labware, or liquids are mentioned as this is testing the underlying API logic rather than implementing an actual protocol.
</about>

---

## tests/opentrons/protocol_api/test_thermocycler_context.py

<about>
This file contains unit tests for the ThermocyclerContext class in the Opentrons Protocol API, specifically testing the Python API wrapper for thermocycler module functionality. It's a test file, not a protocol, that validates various thermocycler operations including temperature control (block and lid), lid position management, profile execution, and status queries. The tests use mocking frameworks (Decoy) to verify that the ThermocyclerContext properly delegates calls to its core implementation and publishes appropriate broker messages. The file tests getter methods for temperature readings, status properties, and cycle/step counts, as well as action methods like opening/closing the lid, setting temperatures, executing thermal profiles, and deactivating components. While it references the thermocycler module extensively, it doesn't specify robot type, pipettes, labware, liquids, or actual protocol steps since it's focused on unit testing the API interface rather than implementing a protocol.
</about>

---

## tests/opentrons/protocol_api/test_magnetic_module_context.py

<about>
This file contains unit tests for the MagneticModuleContext class in the Opentrons Protocol API, specifically testing the Python interface for controlling magnetic modules. It's a test file, not a protocol, that verifies the correct behavior of magnetic module operations including engage/disengage functionality, status reporting, height specifications, and API version compatibility checks. The tests use mocking frameworks (Decoy) to simulate the magnetic module hardware and verify that the API correctly handles different API versions (ranging from 2.2 to 2.14 and MAX_SUPPORTED_VERSION), with particular focus on version-specific behaviors like the deprecation of certain methods in API 2.14+. The file tests core magnetic module functionality but doesn't involve actual protocol execution, pipettes, labware, or liquid handling - it's purely focused on ensuring the MagneticModuleContext class properly interfaces with its underlying core implementation and handles API version constraints correctly.
</about>

---

## tests/opentrons/protocol_api/test_labware.py

<about>
This file is a test suite for the Labware class in the Opentrons Protocol API, not a protocol file. It contains unit tests that verify the functionality of labware-related operations including loading labware, accessing wells, setting offsets, and handling liquids. The tests use mock objects and the Decoy testing framework to validate various API versions (particularly focusing on version compatibility from 2.12 through 2.22 and beyond). The test suite covers features like labware loading from definitions, well grid creation, parent/child relationships between labware, liquid loading and tracking, and API version-specific behaviors. While the tests reference various labware types (including tip racks and adapters) and mention temperature modules in the context of parent relationships, they don't specify particular pipette types, robot models, or actual protocol steps - instead focusing on validating the Labware class interface and its interactions with the core API components.
</about>

---

## tests/opentrons/protocol_api/test_protocol_context.py

<about>
This file is a comprehensive test suite for the ProtocolContext class in the Opentrons Python API, not a protocol file. It tests various methods and functionality of the ProtocolContext public interface including loading instruments (1-channel, 8-channel, and 96-channel pipettes), loading labware, loading modules (Temperature Module, Magnetic Module, Magnetic Block, and Flex Stacker), and other protocol operations. The tests cover both OT-2 and OT-3 (Flex) robot types across different API versions, with specific tests for version-dependent features. While the file doesn't implement an actual protocol, it tests functionality for loading adapters, managing trash bins and waste chutes, moving labware between locations (including off-deck), defining liquids and liquid classes, and various edge cases and error conditions. The tests use mocking extensively to verify the correct behavior of the ProtocolContext class without requiring actual hardware.
</about>

---

## tests/opentrons/protocol_api/test_lc_touch_tip_properties.py

<about>
This file contains unit tests for the TouchTipProperties functionality in the Opentrons protocol API's liquid properties module. It tests the validation and behavior of touch tip parameters used in liquid handling operations, including enabling/disabling touch tip functionality, z-offset positioning, distance from well edge (mm_from_edge), and tip movement speed. The test suite uses property-based testing with Hypothesis to validate that the TouchTipProperties class correctly handles valid numeric inputs and properly rejects invalid values (like None, boolean-looking values, or negative speeds). This is not a protocol file but rather a test file that ensures the touch tip feature - which helps remove droplets from pipette tips by touching the sides of wells - works correctly with appropriate parameter validation. The tests cover instantiation validation, property setters, and edge cases to ensure robust error handling in the liquid handling API.
</about>

---

## tests/opentrons/protocol_api/test_module_context.py

<about>
This file contains unit tests for the ModuleContext class in the Opentrons Protocol API, specifically testing module-related functionality like loading labware and adapters onto modules. It's a test file, not a protocol, that uses pytest and the Decoy mocking framework to verify that ModuleContext methods correctly interact with the underlying core components. The tests cover loading labware (both from parameters and definitions), loading adapters, retrieving module properties (model, type, parent slot), and ensuring proper label sanitization. While the file references various API versions (including MAX_SUPPORTED_VERSION and a specific test with APIVersion(2, 1234)), it doesn't implement an actual protocol or use specific pipettes, modules, fixtures, adapters, labware, or liquids - instead, it mocks these components to test the ModuleContext interface behavior.
</about>

---

## tests/opentrons/protocol_api/test_lc_delay_properties.py

<about>
This file contains unit tests for delay properties in the Opentrons protocol API's liquid handling functionality. It tests the `_build_delay_properties` function and the `DelayProperties` class, which are part of the liquid class definition system. The tests use pytest and hypothesis for property-based testing to validate various aspects of delay properties including: enabling/disabling boolean properties, handling None value combinations during instantiation, validating enabled property with invalid values, testing duration values (must be >= 0), and ensuring proper error handling for bad inputs. This is not a protocol file but rather a test suite that ensures the delay properties functionality works correctly when defining liquid handling behaviors in the Opentrons API.
</about>

---

## tests/opentrons/protocol_api/test_temperature_module_context.py

<about>
This file contains unit tests for the TemperatureModuleContext class in the Opentrons Protocol API, not a protocol file. It tests various temperature module functionalities including setting temperatures, awaiting temperatures, deactivating the heater, and retrieving current/target temperatures and module status. The tests use mock objects and the Decoy testing framework to verify proper interaction between the TemperatureModuleContext and its underlying core components. The file tests API version compatibility, particularly checking that certain methods (like start_set_temperature and await_temperature) require API version 2.3 or higher. While the tests reference temperature module operations, they don't specify robot type (OT-2 or Flex), pipettes, labware, liquids, or other modules - the focus is purely on validating the temperature module's API implementation and ensuring proper command publishing through the broker system.
</about>

---

## tests/opentrons/protocol_api/test_well.py

<about>
This file contains unit tests for the `Well` class in the Opentrons Protocol API, specifically testing the public interface methods and properties of wells within labware. It's a test file, not a protocol, that uses pytest and the Decoy mocking framework to verify that the Well class correctly interacts with its core implementation and properly exposes methods like `top()`, `bottom()`, `center()`, `meniscus()`, `load_liquid()`, and various dimensional properties (diameter, length, width, depth). The tests ensure API version handling (with a minimum of 2.13), proper parent labware references, string representation, and geometric calculations. While the test mentions loading liquids and checking for tips (relevant to pipetting operations), it doesn't specify any particular robot type, pipette channels, modules, fixtures, adapters, or specific labware - it's focused purely on testing the Well class interface functionality.
</about>

---

## tests/opentrons/protocol_api/test_parameter_context.py

<about>
This file is a test suite for the ParameterContext class in the Opentrons Protocol API, not a protocol file. It tests the public interface for parameter handling functionality, including methods to add different parameter types (integer, float, boolean, string, and CSV), set parameter values, and export parameters for both analysis and protocol execution. The tests use mocking (via the Decoy library) to verify that parameter definitions are created correctly, validation is performed (like ensuring unique variable names), and that the ParameterContext properly manages parameter storage and retrieval. The file tests against the MAX_SUPPORTED_VERSION of the API but doesn't involve any actual robot operations, pipettes, modules, labware, or protocol steps - it's purely focused on testing the parameter management system that allows protocols to accept user-defined inputs.
</about>

---

## tests/opentrons/protocol_api/partial_tip_configurations.py

<about>
This file contains test configurations and parametrization data for testing partial tip configurations in the Opentrons Protocol API, specifically for validating nozzle layout configurations across different pipette types. It defines test specifications for both pipette-independent and pipette-reliant nozzle configurations, covering various scenarios including SINGLE, ALL, COLUMN, ROW, PARTIAL_COLUMN, and QUADRANT nozzle layouts. The test data includes validation rules for 8-channel and 96-channel pipettes, with expected error conditions and valid configuration combinations. The file provides structured test cases that verify proper parameter usage, such as ensuring COLUMN/ROW configurations are only used with 96-channel pipettes, PARTIAL_COLUMN is only for 8-channel pipettes, and that certain parameters like 'end', 'front_right', and 'back_left' are only valid with specific nozzle layout styles. It also includes test specifications for how nozzle layout arguments should be converted to instrument core arguments with primary, front-right, and back-left nozzle specifications.
</about>

---

## tests/opentrons/protocol_api/test_liquid_class_properties.py

<about>
This file contains unit tests for the LiquidClass properties functionality in the Opentrons Protocol API, specifically testing the conversion and manipulation of liquid handling properties from shared data models to PAPI (Protocol API) types. The test suite validates the `build_aspirate_properties`, `build_single_dispense_properties`, and `build_multi_dispense_properties` functions, ensuring they correctly parse liquid class definition JSON fixtures (specifically using a glycerol50 fixture) and convert them into appropriate property objects. The tests verify that all property values are correctly extracted, including submerge/retract positions, speeds, delays, flow rates, corrections, air gaps, touch tip settings, and mix parameters, and also test that these properties can be overridden with new values. Additionally, it tests the `LiquidHandlingPropertyByVolume` class which handles volume-based interpolation of liquid handling parameters. This is not a protocol file but rather a test suite for the liquid class properties system that would be used by protocols to define custom liquid handling behaviors.
</about>

---

## tests/opentrons/protocol_api/test_flex_stacker_context.py

<about>
This file contains unit tests for the FlexStackerContext class in the Opentrons Protocol API, specifically testing the Python API wrapper for the Flex Stacker module. The tests verify various methods of the FlexStackerContext including serial number retrieval, fill/empty operations, labware storage management, and API version compatibility (primarily testing API version 2.23 and above). The file uses pytest and the Decoy mocking framework to test the interaction between the FlexStackerContext and its underlying core implementation, ensuring proper argument passing and response handling for methods like `fill()`, `empty()`, `set_stored_labware()`, `get_max_storable_labware()`, and various labware list operations. This is not a protocol file but rather test infrastructure for the Flex robot's stacker module functionality.
</about>

---

## tests/opentrons/protocol_api/test_absorbance_reader_context.py

<about>
This file contains unit tests for the `AbsorbanceReaderContext` class in the Opentrons Protocol API, specifically testing the absorbance plate reader module functionality. It's a test file, not a protocol, that uses pytest and the Decoy mocking framework to verify that the `AbsorbanceReaderContext` properly interacts with its underlying core components. The test sets up mock objects for the absorbance reader core, protocol core, core map, and legacy broker, then tests basic functionality like retrieving the serial number from the absorbance reader module. The API version used in the tests is 2.21, and while the file tests module functionality, it doesn't specify robot type, pipettes, labware, liquids, or protocol steps since it's focused on unit testing the absorbance reader context implementation rather than executing an actual protocol.
</about>

---

## tests/opentrons/util/test_change_notifier.py

<about>
This file contains unit tests for the `ChangeNotifier` class in the Opentrons utility module, which appears to be an asynchronous notification system that allows multiple subscribers to wait for and respond to change events. The test suite verifies three key behaviors: single subscriber notification functionality, multiple subscriber notification with ordering guarantees (testing that subscribers are notified in the order they subscribed), and the ability to handle notifications while subscribers are busy processing previous notifications. This is not a protocol file but rather a testing file for internal Opentrons API infrastructure, so protocol-specific details like API level, robot type, pipettes, modules, fixtures, adapters, labware, liquids, and protocol steps are not applicable (N/A).
</about>

---

## tests/opentrons/util/test_async_helpers.py

<about>
This file is a test suite for the `async_helpers` module in the Opentrons API, specifically testing the `async_context_manager_in_thread()` function. It's not a protocol file but rather unit tests that verify the proper behavior of asynchronous context managers running in separate threads. The test class `TestAsyncContextManagerInThread` contains five test methods that validate: proper entering and exiting of context managers, correct event loop handling and lifetime management, and proper exception propagation from both the `__aenter__` and `__aexit__` methods. The tests ensure that the async context manager utility correctly manages thread-based event loops and handles various edge cases including exceptions. This is infrastructure testing code that supports the Opentrons API's ability to handle asynchronous operations in threaded environments.
</about>

---

## tests/opentrons/util/test_get_union_elements.py

<about>
This file contains unit tests for the `get_union_elements` utility function in the Opentrons codebase. The tests verify that the function correctly extracts type elements from Python typing.Union types, including handling of Annotated types where top-level annotations should be stripped but element-level annotations preserved. The test suite includes parametrized tests for valid inputs (Union types with and without annotations) and tests that ensure the function raises TypeError for invalid inputs like non-type values or non-union types. This is not a protocol file but rather a testing module for internal utility functions used in the Opentrons API.
</about>

---

## tests/opentrons/util/test_broker.py

<about>
This file is a unit test for the `opentrons.util.broker` module, which tests a publish-subscribe messaging pattern implementation. The test file contains two test functions that verify the Broker class's subscription and unsubscription functionality, testing both context manager-based subscriptions (using `with` statements) and manual subscription/unsubscription methods. The tests ensure that callbacks only receive messages while they are actively subscribed, with messages published before subscription or after unsubscription being properly ignored. This is not a protocol file but rather infrastructure testing code for the Opentrons API's internal messaging system.
</about>

---

## tests/opentrons/util/**init**.py

<about>
This file is a Python test module initialization file (`__init__.py`) for the `opentrons.util` package tests, containing only a docstring that indicates it houses tests for the `opentrons.util` module. It is not a protocol file but rather part of the test suite infrastructure. Since this is just a test initialization file with minimal content, it doesn't involve any specific API level, robot type, pipettes, modules, fixtures, adapters, labware, liquids, or protocol steps - all of these categories are N/A for this file.
</about>

---

## tests/opentrons/util/test_linal.py

<about>
This file is a unit test file for linear algebra utility functions in the Opentrons codebase, not a protocol or API documentation file. It tests three mathematical functions: `solve()` which appears to solve transformation matrices, `add_z()` which adds a z-dimension to 2D transformation matrices, and `apply_transform()` which applies transformation matrices to points. The tests use numpy arrays and mathematical operations involving trigonometry (sin, cos, pi) to verify that these linear algebra utilities work correctly for coordinate transformations and matrix operations. This is infrastructure code for the robot's spatial calculations rather than user-facing protocol functionality, so none of the protocol-specific elements (robot type, pipettes, modules, labware, etc.) apply to this file.
</about>

---

## tests/opentrons/util/test_entrypoint_util.py

<about>
This test file validates the functionality of utility functions in the Opentrons API for loading labware definitions and data files from specified file paths. It tests two main functions: `labware_from_paths()` which loads and validates JSON labware definition files from given directories, and `datafiles_from_paths()` which reads arbitrary data files from specified paths. The test creates temporary directories with various test files including valid labware JSON files (using fixtures for a 96-well plate, 24-tube rack, and an irregular labware), invalid JSON files, and binary data files with different encodings. It verifies that the functions correctly parse valid labware definitions, skip invalid files, and properly read data files while preserving their original encoding. This is not a protocol file but rather a unit test for the entrypoint utilities that help load external labware definitions and data files into the Opentrons system.
</about>

---

## tests/opentrons/config/ot3_settings.py

<about>
This file contains test configuration settings for the OT-3 (Flex) robot, specifically dummy settings used for testing purposes. It's not a protocol file but rather a Python configuration file that defines motion settings, current settings, and calibration parameters for the OT-3 Standard model named "Marie Curie". The settings include acceleration values, maximum speeds, and current settings for different throughput modes (low_throughput, high_throughput_1000, high_throughput_200) across various axes (X, Y, Z, P, Q, Z_G). The file also contains calibration settings for z_offset and edge_sense operations, liquid sensing parameters, deck transformation matrices, and various mount offsets for the robot's carriage, right mount, left mount, and gripper. No specific pipettes, modules, fixtures, adapters, labware, liquids, or protocol steps are mentioned as this is a configuration file for testing robot hardware settings rather than an actual protocol.
</about>

---

## tests/opentrons/config/test_advanced_settings.py

<about>
This file is a test suite for the advanced settings functionality in the Opentrons configuration system, not a protocol file. It tests various aspects of the `advanced_settings` module including getting/setting individual settings, retrieving all settings, caching behavior, and restart requirements. The tests cover both OT-2 and Flex (OT-3) robot types, using mock fixtures to simulate different settings configurations and file operations. The test suite verifies that settings can be properly read, written, cached, and filtered by robot type, with specific tests for unknown settings handling, LRU cache invalidation, and per-robot default values. No pipettes, modules, fixtures, adapters, labware, liquids, or protocol steps are involved as this is infrastructure testing code rather than a liquid handling protocol.
</about>

---

## tests/opentrons/config/ot2_settings.py

<about>
This file contains test data for OT-2 robot settings configurations, not a protocol or API documentation file. It defines three dictionary objects (`legacy_dummy_settings`, `migrated_dummy_settings`, and `new_dummy_settings`) that represent different versions of OT-2 configuration settings, likely used for testing configuration migration or settings management functionality. The settings include robot parameters such as motor steps per millimeter for various axes (X, Y, Z, A, B, C), acceleration values, current settings (default, low, and high), mount offsets, serial speed, and pipette configurations. The file appears to be part of the test suite for validating how the Opentrons software handles different versions of OT-2 settings, with the "migrated" settings showing a transition from version 42 to version 4 and introducing a nested structure for current settings with "default" and "2.1" sub-configurations.
</about>

---

## tests/opentrons/config/test_defaults_ot3.py

<about>
This file contains unit tests for the OT-3 (Flex) robot configuration defaults loading system, specifically testing the `defaults_ot3` module's functionality. It's not a protocol file but rather a test suite that validates how default calibration settings, per-pipette values, offset values, and transform values are loaded and handled when building OT-3 configurations. The tests verify that the system correctly handles missing data by applying defaults, preserves user-provided values when they exist, and properly validates data formats and types. The file specifically tests calibration settings (edge sensing, z-offset), motion settings (acceleration, speed, discontinuity values), mount offsets, and machine transforms, ensuring that the configuration building process is robust against malformed or incomplete input data while maintaining backward compatibility.
</about>

---

## tests/opentrons/config/test_defaults_ot2.py

<about>
This file is a test file for the Opentrons OT-2 configuration defaults module, not a protocol file. It contains unit tests that verify the functionality of the `_build_hw_versioned_current_dict` function from the `defaults_ot2` module, which handles motor current configurations for different hardware versions of the OT-2 robot. The test checks various scenarios including legacy current values, default current dictionaries with different hardware versions (like "B" and "2.1"), and ensures the function correctly builds versioned current dictionaries for the robot's motors (X, Y, Z, A, B, C axes). This is part of the testing infrastructure for the OT-2 robot's configuration system and does not involve any actual liquid handling, pipettes, modules, or labware operations.
</about>

---

## tests/opentrons/config/test_gripper_config.py

<about>
This file is a test module for the Opentrons gripper configuration functionality, not a protocol file. It contains unit tests that verify the gripper configuration loading and force-to-duty-cycle conversion functions. The tests specifically check that the Flex Gripper (v1 model) configuration loads correctly with the expected display name "Flex Gripper", and validates the mathematical conversion formula (2.09 * force - 0.282) for forces between 5-20 units, while ensuring that forces outside this range raise ValueError exceptions. This is testing code for the Flex (OT-3) robot's gripper module functionality, but doesn't involve any actual protocol execution, pipettes, labware, liquids, or protocol steps.
</about>

---

## tests/opentrons/config/test_reset.py

<about>
This file is a test suite for the Opentrons configuration reset functionality, not a protocol file. It tests various reset operations for both OT-2 and Flex (OT-3) robots, including resetting boot scripts, pipette offsets, deck calibration, tip length calibrations, gripper offsets, robot attitude, and module calibration. The test file uses pytest fixtures and mocking to verify that appropriate reset functions are called when different reset options are selected. It includes tests for getting reset options based on robot type, resetting with empty sets (no operations), resetting with all options enabled, and individual reset operations like deck calibration and pipette offset resets. The file also includes robot-type-specific tests, such as tip length calibration reset being valid only for OT-2 robots (raising an UnrecognizedOption error for Flex robots).
</about>

---

## tests/opentrons/config/test_robots_config.py

<about>
This file is a test suite for the Opentrons robot configuration system, not a protocol file. It contains unit tests that verify the functionality of loading, migrating, and saving robot configuration files for both OT-2 and OT-3 (Flex) robots. The tests check various scenarios including handling corrupt JSON files, migrating legacy configurations to new formats, round-trip conversion between configuration dictionaries and JSON, loading legacy gantry calibration data, and selecting appropriate current settings based on board revisions. The file imports test data from separate OT-2 and OT-3 settings files and uses pytest for test parameterization. No pipettes, modules, fixtures, adapters, labware, liquids, or protocol steps are mentioned as this is infrastructure testing code rather than a liquid handling protocol.
</about>

---

## tests/opentrons/config/test_advanced_settings_migration.py

<about>
This file is a test suite for the advanced settings migration functionality in the Opentrons configuration system, not a protocol file. It contains pytest fixtures and test cases that verify the migration of configuration settings across 37 different versions (from versionless to v37), ensuring that settings are properly migrated and default values are correctly applied. The test file checks various configuration options including hardware settings (like `shortFixedTrash`, `deckCalibrationDots`, `disableHomeOnBoot`), feature flags (like `enableOT3HardwareController`, `enableErrorRecoveryExperiments`), and system behaviors (like `disableStallDetection`, `estopNotRequired`). The main test functions verify that old settings are properly migrated to the current version while preserving user-configured values and applying new defaults where appropriate. This is infrastructure testing code for the Opentrons software configuration system rather than a liquid handling protocol.
</about>

---

## tests/opentrons/protocol_api_integration/test_transfer_with_liquid_classes.py

<about>
This file is an integration test suite for the Opentrons Protocol API's transfer methods using liquid classes, specifically testing water transfers on the Flex (OT-3) robot with API version 2.24. The test file validates various transfer operations including simple transfers, consolidation, and distribution with different tip policies and configurations. It uses 1-channel pipettes (flex_1channel_50, flex_1channel_1000) and an 8-channel pipette (flex_8channel_50) in the tests. The tests utilize fixtures including a trash bin (A3 position), labware including Opentrons Flex 96 tipracks (50µL and 1000µL), NEST 96-well plates (200µL), and Armadillo 96-well PCR plates (200µL). The liquid used throughout is "water" accessed via the liquid class API. The protocol steps tested include pick_up_tip, aspirate_liquid_class, dispense_liquid_class, drop_tip operations, as well as specialized transfer methods (transfer_with_liquid_class, consolidate_with_liquid_class, distribute_with_liquid_class) with various configurations for tip handling (always, once, never, per source, per destination), liquid presence detection, and multi-dispense operations.
</about>

---

## tests/opentrons/protocol_api_integration/conftest.py

<about>
This file is a pytest configuration file (`conftest.py`) for Opentrons protocol API integration tests, not a protocol file. It provides a test fixture called `simulated_protocol_context` that creates simulated protocol contexts for testing purposes, accepting parameters for API version and robot type (OT-2 or Flex/OT-3). The fixture handles proper cleanup of hardware threads and protocol engine contexts after tests complete, with different cleanup procedures depending on whether the context uses the newer Engine Core API (version 2.14+) or the legacy API. This is testing infrastructure code that supports integration testing of the Opentrons API, ensuring that simulated protocol contexts are properly initialized and cleaned up to prevent thread leaks during test execution.
</about>

---

## tests/opentrons/protocol_api_integration/test_pipette_movement_deck_conflicts.py

<about>
This file contains integration tests for the Opentrons Protocol API, specifically testing deck conflict detection during pipette movements with partial tip configurations on the Flex (OT-3) robot. The tests use API version 2.16 and 2.20 with a 96-channel pipette in various nozzle configurations (COLUMN A1, COLUMN A12, ROW H1, ROW A1, SINGLE, and ALL). The tests verify that PartialTipMovementNotAllowedError is raised when the pipette would collide with tall labware (like tube racks and tiprack adapters), thermocycler lids, or move outside robot bounds. The protocol uses various labware including opentrons_flex_96_tiprack_50ul/200ul, nest_96_wellplate_200ul_flat, opentrons_10_tuberack_falcon_4x50ml_6x15ml_conical, nest_12_reservoir_15ml, nest_1_reservoir_195ml, and opentrons_96_wellplate_200ul_pcr_full_skirt. Modules used include thermocyclerModuleV2, magneticBlockV1, and heaterShakerModuleV1, with the opentrons_flex_96_tiprack_adapter and opentrons_96_deep_well_adapter. The tests perform protocol steps including pick_up_tip, aspirate, dispense, drop_tip, and distribute operations to validate proper collision detection when using partial tip configurations.
</about>

---

## tests/opentrons/protocol_api_integration/test_liquid_classes.py

<about>
This file contains integration tests for the liquid classes API in Opentrons protocol API version 2.24. It tests the creation and property fetching of both built-in and custom liquid classes on the Flex (OT-3) robot. The tests verify that liquid classes can be properly instantiated, their properties accessed (like flow rates and speeds), and that appropriate errors are raised for invalid operations. The tests use both 1-channel (flex_1channel_50) and 8-channel (flex_8channel_50) pipettes with the opentrons_flex_96_tiprack_50ul labware. While not a protocol itself, the tests demonstrate how to load instruments, load labware, get liquid classes (like "water"), define custom liquid classes, and access their transfer properties for specific pipette-tiprack combinations. No modules, fixtures, or adapters are used in these tests, and the only liquid mentioned is "water" as a liquid class example.
</about>

---

## tests/opentrons/protocol_api_integration/**init**.py

<about>
This file is an `__init__.py` file for integration tests of the Opentrons Python Protocol API, not a protocol or API documentation file. It serves as a package initializer and contains a docstring explaining that these integration tests verify the Python Protocol API from the user's perspective, focusing on testing nontrivial interactions between API layers rather than actual robot movements (which are tested elsewhere). The file doesn't contain any actual protocol code, so details about API level, robot type, pipettes, modules, fixtures, adapters, labware, liquids, or protocol steps are N/A.
</about>

---

## tests/opentrons/protocol_api_integration/test_trashes.py

<about>
This file is a test suite for the Opentrons Protocol API's trash handling functionality, specifically testing the behavior of waste chutes and trash bins across different API versions and robot types. It's not a protocol file but rather integration tests that verify how the fixed trash presence and loading conflicts work in different configurations. The tests cover API versions from 2.13 to 2.16 on both OT-2 and Flex robots, examining when fixed trash containers are available (as Labware objects in older versions or TrashBin objects in newer versions) and when they're not supported (Flex with API 2.16+). The tests use both p300_single_gen2 (for OT-2) and flex_1channel_50 (for Flex) pipettes to verify trash container access through the instrument interface. No modules, fixtures, adapters, or liquids are used in these tests. The test scenarios include verifying fixed trash presence, testing automatic trash search functionality when no fixed trash exists, and checking for proper error handling when attempting to load labware onto slot 12 (the traditional fixed trash location) in different API version configurations.
</about>

---

## tests/opentrons/protocol_api_integration/test_modules.py

<about>
This file contains integration tests for the Opentrons Protocol API's module functionality, specifically testing the AbsorbanceReaderV1 module on the Flex robot. The tests verify proper conflict handling when loading or moving labware onto a closed absorbance reader module, ensuring that operations are blocked when the lid is closed and allowed when open. Additionally, it tests the preconditions for reading from the absorbance reader, verifying that the module must be initialized with proper wavelength settings and the lid must be closed before a read operation can be performed. The tests use API version 2.21 on the Flex robot, with the absorbance reader module loaded in position A3, and utilize the "opentrons_96_wellplate_200ul_pcr_full_skirt" labware for testing labware operations. No pipettes, fixtures, adapters, or liquids are used in these tests, as they focus solely on module state management and operation sequencing.
</about>

---

## tests/opentrons/data/testosaur_v3.py

<about>
This file is a test protocol for the Opentrons API version 3.0, named "Testosaur Version 3," which is a variant of a "Dinosaur" protocol used for testing purposes. It's a simple liquid transfer protocol using API level 3.0 that runs on an OT-2 robot (based on the use of "p300_single_gen2" which is OT-2 specific). The protocol uses a single-channel P300 GEN2 pipette mounted on the right side. No modules, fixtures, or adapters are used in this protocol. The labware includes an Opentrons 96-tip rack with 300µL tips in slot 8, a NEST 12-well reservoir with 15mL capacity in slot 1 (source), and a Corning 96-well plate with 360µL capacity in slot 2 (destination). No specific liquids are defined. The protocol steps involve a simple loop that runs 4 times, where for each iteration it picks up a tip, aspirates 50µL from well A1 of the source reservoir, dispenses 50µL into consecutive wells of the destination plate, and returns the tip to its original position in the tip rack.
</about>

---

## tests/opentrons/data/mad_mag_v2.py

<about>
This file is a test protocol for the Magnetic Module using the Opentrons API. It's a protocol file with API level 2.2, designed for the OT-2 robot (based on the API level and module compatibility). The protocol uses a single-channel P300 GEN2 pipette mounted on the right side. The main module used is the Magnetic Module loaded in slot 4. The labware includes an Opentrons 96-well tip rack (300µL) in slot 1 and a NEST 96-well PCR plate (100µL full skirt) loaded on the magnetic module. The protocol demonstrates various magnetic module operations including: transferring 30µL of liquid from well A1 to B1 (1mm above bottom), engaging and disengaging the magnetic module multiple times with different parameters (default engagement, engagement at 30mm height, engagement with -10mm offset, and engagement at 15mm from base). No specific liquids, fixtures, or adapters are mentioned in this test protocol.
</about>

---

## tests/opentrons/data/testosaur_v2_14.py

<about>
This file is a test protocol for the Opentrons platform, specifically a variant of the "Dinosaur" protocol used for testing purposes. It's a protocol file using API level 2.14, designed for the OT-2 robot (based on the API version and lack of Flex-specific features). The protocol uses a 1-channel P1000 pipette mounted on the right side. No modules, fixtures, or adapters are used. The labware includes an Opentrons 96-tip rack with 1000 µL tips and a Corning 96-well plate with 360 µL flat-bottom wells. No specific liquids are defined. The protocol steps are simple: home the robot, pick up a tip, aspirate 100 µL from the bottom of well A1, dispense 100 µL to the bottom of well B1, and drop the tip in the last well of the tip rack.
</about>

---

## tests/opentrons/data/testosaur_v2.py

<about>
This file is a test protocol for the Opentrons platform, specifically a variant of the "Dinosaur" protocol used for testing purposes. It's a Python protocol using API level 2.0, designed for the OT-2 robot (based on the API level and lack of Flex-specific features). The protocol uses a 1-channel P1000 pipette mounted on the right side. No modules, fixtures, or adapters are used. The labware includes an Opentrons 96-tip rack with 1000 µL tips in slot 1 and a Corning 96-well plate (360 µL flat bottom) in slot 2. No specific liquids are defined. The protocol steps are: home the robot, pick up a tip, aspirate 100 µL from the bottom of well A1, dispense 100 µL to the bottom of well B1, and drop the tip at the top of the last well in the tip rack.
</about>

---

## tests/opentrons/data/ot2_drop_tip.py

<about>
This file is a simple OT-2 protocol that demonstrates basic tip handling operations. It's a minimal protocol with API level 2.16 for the OT-2 robot that uses an 8-channel P300 GEN2 pipette mounted on the right mount. The protocol loads a single Opentrons 96-tip rack with 300µL tips in slot 5. The only protocol steps are picking up a tip and immediately dropping it - essentially a tip pickup/drop test. No modules, fixtures, adapters, or liquids are used in this protocol.
</about>

---

## tests/opentrons/data/testosaur.py

<about>
This file is a test protocol for the Opentrons platform named "Testosaur," which appears to be a simplified variant of a "Dinosaur" protocol used for testing purposes. It's written using the older Opentrons API (not API v2), as evidenced by the import statements and syntax. The protocol is designed for the OT-2 robot and uses a P300 Single-channel pipette mounted on the right. The protocol uses a 200µL tip rack in slot 5 and two 96-well PCR plates in slots 8 and 11. No modules, fixtures, adapters, or specific liquids are mentioned. The protocol steps are minimal: it picks up a tip, then for each PCR plate, aspirates 10µL from the first well (A1) and dispenses it 5mm above the last well (H12), and finally drops the tip. The file includes commented-out code for testing precision movements between deck positions.
</about>

---

## tests/opentrons/data/bug_aspirate_tip.py

<about>
This file is a test protocol for bug 7552 that demonstrates an issue where the simulation allows aspirating and dispensing on a tip rack, which should not be permitted. It's a minimal protocol using API level 2.11 for the OT-2 robot (based on the API level and lack of Flex-specific features). The protocol uses a single-channel P300 pipette on the left mount and loads a GEB 96-tip rack (10µL) in slot 4. The protocol attempts to perform a transfer operation of 5µL from well A1 to well B1 of the tip rack itself, which is incorrect behavior as tip racks should only be used for picking up tips, not for liquid handling operations.
</about>

---

## tests/opentrons/data/testosaur-gen2-v2.py

<about>
This file is a test protocol for the Opentrons platform, specifically a simplified variant of the "Dinosaur" protocol used for testing purposes. It's an OT-2 protocol using API level 2.3, which employs a p300_single_gen2 (1-channel) pipette mounted on the right side. The protocol uses two labware items: an Opentrons 96-tip rack with 300µL tips and a Corning 96-well plate with 360µL flat-bottom wells. No modules, fixtures, adapters, or specific liquids are mentioned. The protocol executes a simple liquid transfer sequence: it homes the robot, picks up a tip, aspirates 10µL from the bottom of well A1, dispenses 10µL to the bottom of well B1, and then drops the tip at the top of the last well in the tip rack.
</about>

---

## tests/opentrons/data/**init**.py

<about>
This file (`tests/opentrons/data/__init__.py`) is an empty Python initialization file that marks the `data` directory as a Python package within the Opentrons test suite. It contains no code, protocols, or documentation - it simply exists to allow Python to recognize the directory as a package so that data files or modules within this directory can be imported in tests. This is not a protocol file and contains no information about API levels, robot types, pipettes, modules, fixtures, adapters, labware, liquids, or protocol steps.
</about>

---

## tests/opentrons/data/testosaur_with_rtp.py

<about>
This file is a test protocol for the Opentrons platform that demonstrates the use of Runtime Parameters (RTP). It's a simple liquid transfer protocol with API level 2.18 that allows users to configure parameters at runtime. The protocol uses a single-channel P300 Gen2 pipette that can be mounted on either the left or right mount (configurable via RTP). The labware includes an Opentrons 96-tip rack (300µL), a NEST 12-well reservoir (15mL) as the source, and a Corning 96-well plate (360µL) as the destination. The protocol performs a basic liquid transfer operation where it picks up tips, aspirates 50µL from well A1 of the source reservoir, dispenses into destination wells, and returns tips, repeating this process for a user-defined number of samples (1-6, default 3). No modules, fixtures, adapters, or specific liquids are mentioned in this protocol.
</about>

---

## tests/opentrons/data/python_v2_custom_lw.py

<about>
This file is a test protocol for the Opentrons Python API v2.0 that demonstrates custom labware functionality. It's a simple liquid transfer protocol designed for testing purposes, specifically testing custom labware definitions. The protocol uses API level 2.0 and is compatible with the OT-2 robot (based on the pipette model used). It employs a single-channel P300 GEN2 pipette mounted on the right side. The protocol loads an Opentrons 96-well tiprack with 300µL tips and a custom labware called "fixture_96_plate" from the "fixture" namespace. The protocol steps are straightforward: it homes the robot, picks up a tip, aspirates 10µL from the bottom of well A1 in the custom plate, dispenses 10µL to the bottom of well B1, and drops the tip at the top of the last well in the tiprack. No modules, adapters, or specific liquids are mentioned in this test protocol.
</about>

---

## tests/opentrons/protocols/test_parse.py

<about>
This file is a comprehensive test suite for the Opentrons protocol parsing functionality, specifically testing the `parse` module that handles both Python and JSON protocol files. It tests various aspects of protocol parsing including API version detection (from APIv1 through v2.x), metadata and requirements validation, robot type specification (OT-2 and Flex/OT-3), and error handling for malformed protocols. The test suite covers edge cases like protocols with missing or incorrectly formatted apiLevel declarations, multiple run functions, invalid robotType specifications, and JSON schema version validation. It uses pytest parametrization extensively to test multiple scenarios and includes tests for both string and bytes protocol inputs, bundle parsing with extra labware and data, and legacy parsing modes. The file doesn't contain an actual protocol but rather validates the parsing logic that would process real protocols, ensuring proper extraction of metadata, API levels, and robot compatibility information.
</about>

---

## tests/opentrons/protocols/**init**.py

<about>
This file (`tests/opentrons/protocols/__init__.py`) is an empty Python initialization file used to mark the `protocols` directory as a Python package within the Opentrons test suite. It contains no code, protocols, or documentation - it simply exists to allow Python to recognize the directory as a package for importing test modules. This is not a protocol file and contains no information about API levels, robot types, pipettes, modules, fixtures, adapters, labware, liquids, or protocol steps.
</about>

---

## tests/opentrons/protocols/test_bundle.py

<about>
This file contains unit tests for the Opentrons protocol bundle functionality, specifically testing the `bundle.py` module's ability to parse and create protocol bundles (ZIP files containing protocols and associated files). The test suite includes four test functions that verify error handling for various invalid bundle scenarios: bundles with no root files, bundles missing an entrypoint protocol, bundles with conflicting labware definitions, and a test for successfully writing/reading bundle contents. This is not a protocol file but rather a test file for the bundle extraction and creation functionality, using pytest fixtures and the zipfile module to validate that the bundle parsing correctly identifies and reports errors in malformed protocol bundles.
</about>

---

## tests/opentrons/protocol_api/core/**init**.py

<about>
This file is a Python package initialization file (`__init__.py`) for the test suite of Opentrons Protocol API's internal core interfaces, not a protocol file or API documentation. It simply contains a docstring indicating that this directory contains tests for the Protocol API's core internal interfaces. The file itself is empty except for the docstring and serves as a package marker for Python's import system. Since this is a test infrastructure file rather than a protocol or documentation, none of the protocol-specific details (API level, robot type, pipettes, modules, fixtures, adapters, labware, liquids, or protocol steps) apply to this file.
</about>

---

## tests/opentrons/protocol_api/core/test_well_grid.py

<about>
This file contains unit tests for the WellGrid class in the Opentrons Protocol API core module. It tests the functionality of creating well grids from column data and verifying that the grid correctly transposes columns into rows, handling both symmetric and asymmetric well layouts. The tests cover edge cases including empty grids, standard rectangular grids, and asymmetric grids where columns have different numbers of wells (both top-aligned and bottom-aligned scenarios). This is not a protocol file but rather test infrastructure for the API's well grid functionality, so it doesn't involve any specific robot types, pipettes, modules, fixtures, adapters, labware, liquids, or protocol steps.
</about>

---

## tests/opentrons/protocol_api/core/test_core_map.py

<about>
This file contains unit tests for the `LoadedCoreMap` class in the Opentrons Protocol API core module. The tests verify the functionality of a mapping system that associates core objects (like `LabwareCore` and `ModuleCore`) with their corresponding API objects (like `Labware` and `MagneticModuleContext`). The test suite covers basic operations including getting nothing from an empty map, adding and retrieving labware and modules, handling missing keys with exceptions, and the get-or-add functionality that can build and cache objects on demand. This is not a protocol file but rather infrastructure testing code that ensures the proper functioning of the internal mapping mechanism used by the Opentrons API to manage loaded labware and modules during protocol execution.
</about>

---

## tests/opentrons/protocols/api_support/test_instrument.py

<about>
This file is a test suite for the Opentrons API's instrument validation functions, specifically testing `validate_takes_liquid` and `validate_tiprack` functions from the `opentrons.protocols.api_support.instrument` module. It's not a protocol file but rather unit tests that verify proper validation of liquid handling operations and tip rack compatibility. The tests use a ProtocolContext to load various labware including well plates (corning_96_wellplate_360ul_flat), tip racks (opentrons_96_tiprack_300ul, opentrons_flex_96_tiprack_200ul), and adapters (opentrons_96_pcr_adapter), and include tests for both OT-2 and Flex (OT-3) robots. The tests check that the validation functions properly reject operations like aspirating/dispensing to tip racks, modules (when reject_module=True), and adapters (when reject_adapter=True), while allowing operations on valid labware like well plates. The file also tests pipette-tip rack compatibility validation, checking for mismatches between pipettes (p1000_96, p50_single_flex, p20_single_gen2) and tip racks, with appropriate warning messages logged when incompatibilities are detected.
</about>

---

## tests/opentrons/protocols/api_support/**init**.py

<about>
This file is an empty Python `__init__.py` file located in the `tests/opentrons/protocols/api_support/` directory. As an empty initialization file, it serves to mark the `api_support` directory as a Python package within the test suite structure. This is not a protocol file but rather a structural component of the Opentrons API test framework. Since it contains no code, there are no API levels, robot types, pipettes, modules, fixtures, adapters, labware, liquids, or protocol steps to report - all of these categories are N/A for this empty initialization file.
</about>

---

## tests/opentrons/protocols/api_support/test_util.py

<about>
This file contains unit tests for utility functions in the Opentrons API support module, specifically testing the `AxisMaxSpeeds` class, `build_edges` function, and `find_value_for_api_version` function. It's not a protocol file but rather test code that validates the behavior of API utilities. The tests cover functionality for OT-2 robots, including edge building for both left and right mount pipettes, and verify proper handling of axis speed limits and API version compatibility. The tests use a Corning 96-well plate (360µL flat bottom) as test labware and include scenarios with a magnetic module in various deck positions. While the tests reference both 1-channel pipettes (through Mount.LEFT and Mount.RIGHT), they don't execute actual liquid handling operations but rather test the underlying utility functions that support protocol execution.
</about>

---

## tests/opentrons/protocols/api_support/test_tip_tracker.py

<about>
This file contains unit tests for the TipTracker class in the Opentrons API, which manages tip usage tracking for pipettes during protocol execution. It's a test file, not a protocol, that verifies the functionality of tracking which tips have been used and which are available in a tip rack. The tests cover various scenarios including using single tips, using multiple tips with multi-channel pipettes (8-channel), selecting the next available tip, returning tips, and handling edge cases like attempting to use already-used tips or returning tips to full racks. The file uses pytest fixtures to set up test data including well ordering (A1-H12 format typical of 96-well plates) and mock well objects that track their tip status. While the tests reference multi-channel functionality (particularly 8-channel operations), they don't specify robot type, modules, fixtures, adapters, specific labware, or liquids as this is testing internal tip tracking logic rather than actual protocol execution.
</about>

---

## tests/opentrons/protocols/api_support/test_labware_like.py

<about>
This file is a test suite for the `LabwareLike` class in the Opentrons API, which provides a wrapper interface for handling different types of labware-related objects in a uniform way. The test file validates the functionality of the `LabwareLike` class across various object types including labware, wells, modules, slots, OFF_DECK locations, and None values. It tests core functionality such as parent-child relationships, object type identification, module parent retrieval, and first parent resolution, including edge cases like recursion cycles. The tests use pytest fixtures to create test objects including a USASCIENTIFIC 12-well reservoir, a Temperature Module V2, and combinations thereof. This is not a protocol file but rather unit tests for the API's internal labware handling infrastructure, and therefore doesn't involve actual liquid handling operations, specific pipettes, or protocol steps.
</about>

---

## tests/opentrons/protocols/models/**init**.py

<about>
This file (`tests/opentrons/protocols/models/__init__.py`) is an empty Python initialization file used to mark the `models` directory as a Python package within the Opentrons protocol testing framework. It contains no actual code or content, serving only as a structural element in the test suite hierarchy. This is not a protocol file, so questions about API level, robot type, pipettes, modules, fixtures, adapters, labware, liquids, and protocol steps are N/A.
</about>

---

## tests/opentrons/protocols/models/test_json_protocol.py

<about>
This file is a test module for the JSON protocol model validation in the Opentrons API, not a protocol file itself. It contains a parameterized test function that validates JSON protocol models across different protocol versions (3, 4, and 5) using various test fixtures. The test loads JSON protocol fixtures, validates them against the protocol model schema using Pydantic, and ensures the parsed model can be correctly serialized back to match the original JSON structure. This is part of the testing infrastructure to ensure JSON protocols are properly parsed and validated across different API versions, but it doesn't contain any actual protocol implementation, pipette usage, module specifications, or liquid handling steps.
</about>

---

## tests/opentrons/protocols/execution/test_execute_json_v4.py

<about>
This file is a test suite for the JSON protocol execution module (v4) in the Opentrons API, specifically testing the execution of JSON-formatted protocols. It contains unit tests that verify the proper dispatching and execution of various commands including pipette operations (aspirate, dispense, blowout, pick up tip, drop tip, touch tip), module operations for magnetic modules (engage/disengage magnet), temperature modules (set temperature, deactivate, await temperature), and thermocycler modules (set block/lid temperature, open/close lid, run profiles). The tests use mock objects to verify that commands are properly parsed and dispatched to the appropriate handler functions, and include validation tests to ensure thermocycler commands follow proper synchronous behavior patterns (e.g., await commands must follow their corresponding set commands). While this is a test file rather than a protocol, it references both OT-2 and Flex robots (with an OT-2-specific test), and tests functionality for all module types but doesn't specify particular pipette channels, labware, liquids, fixtures, or adapters.
</about>

---

## tests/opentrons/protocols/execution/test_execute_json_v5.py

<about>
This file is a unit test for the JSON protocol executor (version 5) in the Opentrons API, specifically testing the `_move_to_well` function with and without optional parameters. It's not a protocol file but rather a test file that verifies the correct behavior of pipette movement commands when executing JSON-based protocols. The test uses mock objects to simulate pipette movements and well interactions, testing scenarios where a pipette moves to a well with optional offset coordinates, force_direct, and minimum_z_height parameters. The file references the InstrumentContext class which represents pipettes in the Opentrons API, though it doesn't specify whether it's for 1-channel, 8-channel, or 96-channel pipettes. No specific robot type (OT-2 or Flex), modules, fixtures, adapters, labware, or liquids are mentioned in this test file, as it focuses purely on testing the movement logic rather than actual protocol execution.
</about>

---

## tests/opentrons/protocols/execution/**init**.py

<about>
This is an empty Python `__init__.py` file located in the test directory for Opentrons protocol execution tests. As an empty initialization file, it serves to make the `tests/opentrons/protocols/execution` directory a Python package, allowing test modules within this directory to be imported. This is not a protocol file but rather a structural component of the test suite architecture. Since it contains no code, there are no API levels, robot types, pipettes, modules, fixtures, adapters, labware, liquids, or protocol steps to report - all aspects are N/A for this empty initialization file.
</about>

---

## tests/opentrons/protocols/execution/test_execute_json_v3.py

<about>
This file contains unit tests for the JSON protocol execution module (execute_json_v3.py) in the Opentrons API, specifically testing the execution of JSON protocol version 3 commands. It's not a protocol file itself but rather tests for protocol execution functionality. The tests cover various liquid handling operations including aspirate, dispense, air gap, blow out, pick up tip, drop tip, touch tip, delay, and move to slot commands. The file tests both individual command functions and the overall dispatch mechanism that routes JSON commands to their corresponding execution functions. It uses mock objects extensively to test the behavior without requiring actual hardware, and includes tests for loading pipettes and labware from JSON definitions. The tests reference both single-channel pipettes (p10_single, p50_single) in the examples, though the actual protocol execution being tested could support any pipette type. No specific modules, fixtures, adapters, or liquids are mentioned as this is testing infrastructure rather than an actual protocol.
</about>

---

## tests/opentrons/protocols/execution/test_execute_python.py

<about>
This file is a test suite for the Python protocol execution module in the Opentrons API, specifically testing the `execute_python.py` module. It contains unit tests that verify proper validation of protocol run functions (ensuring they accept the correct parameters), successful protocol execution, error handling for malformed protocols, exception handling within protocols, and runtime parameter (RTP) extraction and override functionality. The tests use mock protocols with API level 2.0 and include specific test cases for OT-2 robots, though no specific pipettes, modules, fixtures, adapters, or labware are mentioned in the actual test implementations. The file tests protocol execution scenarios including valid protocols (like "testosaur_v2.py"), protocols with runtime parameters ("testosaur_with_rtp.py"), and various error conditions such as protocols with incorrect function signatures or exceptions raised during execution.
</about>

---

## tests/opentrons/protocols/parameters/test_parameter_definition.py

<about>
This file contains unit tests for parameter definition functionality in the Opentrons API, specifically testing the creation and validation of different parameter types (integer, float, boolean, and string) used in protocol parameters. It tests the `create_int_parameter`, `create_float_parameter`, `create_bool_parameter`, and `create_str_parameter` functions, verifying that they properly validate inputs, handle edge cases (like values outside allowed ranges), and correctly convert to Protocol Engine parameter types. The tests use mocking (via Decoy) to isolate the parameter definition logic from the validation functions, and verify that parameters are created with correct display names, variable names, descriptions, units, allowed values, and default values. This is not a protocol file but rather test infrastructure for the parameter system that protocols can use to define customizable parameters.
</about>

---

## tests/opentrons/protocols/parameters/test_csv_parameter_interface.py

<about>
This file contains unit tests for the CSVParameter class in the Opentrons protocols parameters module, testing various CSV file parsing scenarios including files with quotes, different delimiters, empty rows, and trailing newlines. It's not a protocol file but rather a test suite that validates CSV parameter functionality across different API versions (using MAX_SUPPORTED_VERSION). The tests cover edge cases like Windows-style line endings, mixed quote formats, preceding spaces, and dialect detection, ensuring the CSV parsing interface works correctly for protocol parameters. No specific robot type, pipettes, modules, fixtures, adapters, labware, or liquids are mentioned as this is testing infrastructure code rather than an actual protocol.
</about>

---

## tests/opentrons/protocols/parameters/test_validation.py

<about>
This file is a test suite for the validation module in the Opentrons protocols parameters system, not a protocol file. It contains unit tests that verify the validation functions for protocol parameters, including tests for validating variable names (ensuring uniqueness and proper Python naming conventions), display names and descriptions (checking character limits), unit strings, parameter options (validating constraints like min/max values and choices), and type conversions. The test file uses pytest to check both successful validation cases and error conditions, ensuring that appropriate exceptions (ParameterNameError, ParameterValueError, ParameterDefinitionError) are raised when invalid inputs are provided. This is testing infrastructure code rather than an actual protocol, so it doesn't involve any robot types, pipettes, modules, fixtures, adapters, labware, liquids, or protocol steps.
</about>

---

## tests/opentrons/protocols/parameters/**init**.py

<about>
This is an empty Python `__init__.py` file located in the test directory for Opentrons protocol parameters. As an empty initialization file, it serves to make the `tests/opentrons/protocols/parameters` directory a Python package, allowing Python to recognize and import modules from this test directory. This file contains no actual code, protocol definitions, or test implementations - it simply exists for Python package structure purposes. Since it's an empty file, none of the typical protocol elements (API level, robot type, pipettes, modules, fixtures, adapters, labware, liquids, or protocol steps) apply here.
</about>

---

## tests/opentrons/protocols/parameters/test_csv_parameter_definition.py

<about>
This file contains unit tests for the CSV Parameter Definition functionality in the Opentrons API, specifically testing the creation, validation, and behavior of CSV parameters that can be used in protocols. The test file verifies that CSV parameters can be properly created with display names, variable names, and descriptions, that they can store byte string values and file information, and that they correctly convert to protocol engine types and interface objects for use during protocol execution. It uses pytest and the Decoy mocking framework to test the CSVParameterDefinition class and its create_csv_parameter factory function, ensuring proper validation of inputs and handling of runtime requirements when CSV values are accessed. This is not a protocol file but rather test infrastructure for the CSV parameter feature that allows protocols to accept CSV file inputs as runtime parameters.
</about>

---

## tests/opentrons/protocols/geometry/test_frustum_helpers.py

<about>
This test file validates the mathematical functions used for calculating liquid volumes and heights in various well geometries (frustums) within the Opentrons protocol engine. It tests helper functions that handle different well shapes including cuboidal frustums (rectangular), conical frustums (circular), and spherical segments, ensuring accurate volume-to-height and height-to-volume conversions. The file uses pytest and hypothesis for property-based testing, creating fake well geometries with multiple segments and verifying that the mathematical calculations for cross-sectional areas, polynomial roots, and volume/height relationships are correct. It also tests edge cases like finding heights at volume boundaries and handling invalid height values. This is not a protocol file but rather a unit test suite for the geometric calculation utilities that support liquid handling operations in the Opentrons system.
</about>

---

## tests/opentrons/protocols/geometry/**init**.py

<about>
This is an empty Python `__init__.py` file located in the test directory for Opentrons protocols geometry module. As an empty initialization file, it serves to make the `tests/opentrons/protocols/geometry` directory a Python package, allowing test modules within this directory to be imported. This is not a protocol file but rather a structural component of the test suite architecture. Since it contains no code, there are no API levels, robot types, pipettes, modules, fixtures, adapters, labware, liquids, or protocol steps to report - all aspects are N/A for this empty initialization file.
</about>

---

## tests/opentrons/protocols/geometry/test_geometry.py

<about>
This test file validates the geometry planning functions in the Opentrons Python Protocol API, specifically testing path planning for pipette movements, safe height calculations, and deck layout interactions. It's not a protocol but a test suite that focuses on OT-2 robots (as noted by the OT-2-only fixtures and comments about legacy deck support). The tests use various labware including "opentrons_96_tiprack_1000ul", "corning_96_wellplate_360ul_flat", and "usascientific_12_reservoir_22ml", and reference modules like the Thermocycler (V1), Temperature Module (V2), and Magnetic Module (V2) for testing collision avoidance and transforms. The file tests critical movement planning features including arc-based movements between wells, direct movements, critical point handling, minimum z-height enforcement, thermocycler dodging logic, and instrument maximum height constraints, all essential for safe and efficient liquid handling operations.
</about>

---

## tests/opentrons/protocols/geometry/test_planning.py

<about>
This file contains unit tests for the protocol geometry planning module in the Opentrons API, specifically testing the `get_move_type` function. It's not a protocol file but rather a test suite that verifies the correct identification of different movement types (GENERAL_ARC, IN_LABWARE_ARC, and DIRECT) based on source and destination locations. The tests check various scenarios including movements between different labware, movements within the same labware between wells, movements within the same well (top to bottom), and the effect of the `force_direct` parameter. The file uses pytest fixtures for minimal labware objects (`min_lw` and `min_lw2`) but doesn't involve actual protocol execution, pipettes, modules, fixtures, adapters, or liquids - it's purely focused on testing the geometric planning logic for robot movements.
</about>

---

## tests/opentrons/protocols/advanced_control/**init**.py

<about>
This file is an empty Python `__init__.py` file located in the `tests/opentrons/protocols/advanced_control/` directory. As an empty initialization file, it serves to mark the `advanced_control` directory as a Python package within the test suite structure. This is not a protocol file but rather a structural component of the Opentrons test framework. Since the file contains no code, there are no API levels, robot types, pipettes, modules, fixtures, adapters, labware, liquids, or protocol steps to report - all of these categories are N/A for this empty initialization file.
</about>

---

## tests/opentrons/protocols/duration/test_estimator.py

<about>
This file is a test suite for the DurationEstimator class in the Opentrons protocols module, not a protocol file. It contains unit tests that verify the time estimation functionality for various protocol commands including pick up tip, drop tip, blow out, touch tip, delay, and temperature control operations for both the Temperature Module and Thermocycler. The tests use mock objects to simulate InstrumentContext and Location objects, and verify that the estimator correctly calculates durations for different operations like deck movements (testing various slot-to-slot movements with different speeds), temperature changes (testing heating/cooling rates across different temperature thresholds), and thermocycler operations (lid open/close, temperature changes). The file doesn't implement an actual protocol but rather ensures the duration estimation system works correctly for protocol planning purposes.
</about>

---

## tests/opentrons/protocols/duration/**init**.py

<about>
This file (`tests/opentrons/protocols/duration/__init__.py`) is an empty Python initialization file used to mark the `duration` directory as a Python package within the Opentrons test suite. It contains no actual code or content, serving only as a structural element in the test framework hierarchy. This is not a protocol file, so details about API level, robot type, pipettes, modules, fixtures, adapters, labware, liquids, or protocol steps are N/A.
</about>

---

## tests/opentrons/protocols/fixtures/bundled_protocols/simple_bundle/custom_labware.json

<about>
This file is a custom labware definition JSON file, not a protocol file. It defines a fake/example custom labware with 12 rectangular wells arranged in a single row (A1-A12) in a trough format. The labware has dimensions of 127.76 x 85.8 x 44.45 mm, with each well having a rectangular shape, 42.16 mm depth, and 22,000 µL (22 mL) total liquid volume. The labware is categorized as a reservoir, uses schema version 2, and includes metadata indicating it's not a tiprack and is not magnetic module compatible. The definition includes precise well positioning coordinates and specifies that all wells have a V-shaped bottom. This appears to be a test fixture used in the Opentrons testing framework for validating bundled protocol functionality with custom labware definitions.
</about>

---

## tests/opentrons/protocols/fixtures/bundled_protocols/simple_bundle/protocol.py

<about>
This file is a simple bundled protocol for the Opentrons platform that demonstrates reading data from a bundled file and performing liquid transfers. It's an OT-2 protocol with API level 2.0 that uses a single-channel P10 pipette. The protocol loads an Opentrons 96-tip rack (10µL) and a custom labware plate from the "custom_beta" namespace. No modules, fixtures, or adapters are used. The protocol reads comma-separated volume values from a bundled text file ("data.txt"), then performs a series of transfers from well A1 to well A4 of the custom plate, using the volumes specified in the data file. This demonstrates how to use bundled data files within a protocol to drive liquid handling operations.
</about>

---

## tests/opentrons/protocols/fixtures/bundled_protocols/simple_bundle/data.txt

<about>
This file is a simple test data file containing the text "1,2,3" and is not a protocol file. It appears to be a fixture file used for testing bundled protocols in the Opentrons system, likely serving as sample data that can be read by test protocols. The file contains no protocol information, API level specifications, robot type requirements, pipette configurations, modules, fixtures, adapters, labware specifications, liquid definitions, or protocol steps - it is simply a plain text file with comma-separated values used for testing purposes.
</about>

---

## tests/opentrons/protocols/fixtures/bundled_protocols/missing_labware_bundle/protocol.py

<about>
This file is a test protocol for the Opentrons API that appears to be testing a scenario with missing labware bundle. It's a simple protocol that uses API level not explicitly specified (but uses the modern ProtocolContext import), compatible with OT-2 robots (based on the pipette model). The protocol uses a P10 single-channel (1-channel) pipette mounted on the left mount. No modules, fixtures, or adapters are used. The labware includes an Opentrons 96-tip rack with 10µL tips in slot 3 and a Bio-Rad 96-well plate with 200µL PCR wells in slot 1. No specific liquids are defined. The protocol performs a single transfer step of 5µL from well A1 to well B1 of the plate, with the pipette automatically handling tip pickup and liquid transfer through the transfer method.
</about>

---

## tests/opentrons/protocols/advanced_control/transfers/test_common_functions.py

<about>
This file contains unit tests for common utility functions used in the Opentrons transfer functionality, specifically testing parameter validation and volume constraint expansion functions. It's a test file, not a protocol, that validates the behavior of `check_valid_volume_parameters()` which ensures disposal volumes and air gaps don't exceed pipette capacity, and tests two volume expansion functions (`expand_for_volume_constraints()` and `expand_for_volume_constraints_for_liquid_classes()`) that break down large volume transfers into smaller chunks that fit within pipette maximum volume constraints. The tests use pytest parametrization to verify various edge cases and ensure the functions correctly handle volume splitting when transfers exceed pipette capacity, with the liquid class version also accounting for air gaps in its calculations.
</about>

---

## tests/opentrons/protocols/advanced_control/transfers/labware_well_fixtures.py

<about>
This file is a test fixture that provides well naming data structures for testing purposes in the Opentrons API. It contains two constants: `WELLS_BY_COLUMN_96` which defines all well names for a 96-well plate organized by columns (12 columns × 8 rows, from A1-H12), and `WELLS_BY_COLUMN_384` which defines all well names for a 384-well plate organized by columns (24 columns × 16 rows, from A1-P24). This is not a protocol file but rather test data used to support unit tests for transfer operations and labware well handling in the Opentrons advanced control system.
</about>

---

## tests/opentrons/protocols/advanced_control/transfers/**init**.py

<about>
This file is an empty Python `__init__.py` file located in the test directory for Opentrons' advanced control transfers functionality. It serves as a package initializer to make the `transfers` directory a Python package within the test suite structure. Since the file is empty, it doesn't contain any protocol code, API level specifications, robot type information, pipette configurations, modules, fixtures, adapters, labware, liquids, or protocol steps. This is simply a structural file used for Python's package management system in the testing framework.
</about>

---

## tests/opentrons/protocols/advanced_control/transfers/test_transfers.py

<about>
This file is a comprehensive test suite for the Transfer class in the Opentrons API, specifically testing advanced liquid transfer functionality. It's not a protocol but rather unit tests that verify the behavior of transfer operations including basic transfers, distribute, and consolidate modes with various options like touch tip, blow out, air gap, and mixing strategies. The tests are marked as OT-2 only and use both single-channel (p300_single) and multi-channel (p300_multi) pipettes mounted on right and left positions respectively. The test fixtures load standard labware including biorad_96_wellplate_200ul_pcr, corning_96_wellplate_360ul_flat, corning_384_wellplate_112ul_flat, and opentrons_96_tiprack_300ul tipracks. The tests verify various transfer scenarios including default transfers, uneven transfers, location-based transfers, different tip strategies (ONCE, NEVER, ALWAYS), and edge cases like zero volume transfers and oversized transfers that exceed pipette capacity. No modules, fixtures, adapters, or specific liquids are used in these tests, which focus on validating the transfer planning logic and command generation rather than actual liquid handling execution.
</about>

---

## tests/opentrons/protocols/advanced_control/transfers/test_transfer_liquid_utils.py

<about>
This file contains unit tests for the `transfer_liquid_utils` module in the Opentrons API, specifically testing utility functions used in advanced liquid transfer operations. It's a test file, not a protocol, that validates functions for checking pipette locations relative to liquid levels and grouping wells for multi-channel transfers. The tests cover both OT-2 and Flex (OT-3) robots, testing various pipette configurations including 8-channel and 96-channel pipettes with different nozzle maps (full, single column, single row configurations). The file uses mock objects to simulate 96-well and 384-well labware formats, and tests edge cases like liquid height validation, location checking for submerge/retract operations, and well grouping algorithms for multi-channel transfers. No actual modules, fixtures, adapters, or liquids are used since this is a test file with mocked components.
</about>

---
