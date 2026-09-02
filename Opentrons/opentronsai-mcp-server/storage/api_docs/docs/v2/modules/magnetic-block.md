# Load the Magnetic Block in deck slot D1

magnetic_block = protocol.load_module(
    module_name="magneticBlockV1", location="D1"
)

# Load a 96-well plate on the magnetic block

mag_plate = magnetic_block.load_labware(
    name="biorad_96_wellplate_200ul_pcr"
)

# Use the gripper to move labware

protocol.move_labware(mag_plate, new_location="B2", use_gripper=True)
```
*New in version 2.15*
