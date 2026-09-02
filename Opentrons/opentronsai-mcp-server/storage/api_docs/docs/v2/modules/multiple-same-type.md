## Multiple modules on Flex

In this example, `temperature_module_1` loads first because it's connected to USB port 2. `temperature_module_2` loads next because it's connected to USB port 6.
```python
from opentrons import protocol_api

requirements = {"robotType": "Flex", "apiLevel": "2.28"}

def run(protocol: protocol_api.ProtocolContext):
  # Load Temperature Module 1 in deck slot D1 on USB port 2
  temperature_module_1 = protocol.load_module(
    module_name="temperature module gen2",
    location="D1")

  # Load Temperature Module 2 in deck slot C1 on USB port 6
  temperature_module_2 = protocol.load_module(
    module_name="temperature module gen2",
    location="C1")
```
The Temperature Modules are connected as shown here:

<figure markdown style="width: 50%;">
![Flex USB Order](../img/modules/flex-usb-order.png)
</figure>

## Multiple modules on OT-2

In this example, `temperature_module_1` loads first because it's connected to USB port 1. `temperature_module_2` loads next because it's connected to USB port 2.
```python
from opentrons import protocol_api

metadata = {"apiLevel": "2.28"}

def run(protocol: protocol_api.ProtocolContext):
    # Load Temperature Module 1 in deck slot C1 on USB port 1
    temperature_module_1 = protocol.load_module(
        load_name="temperature module gen2", location="1"
    )

    # Load Temperature Module 2 in deck slot D3 on USB port 2
    temperature_module_2 = protocol.load_module(
        load_name="temperature module gen2", location="3"
    )
```
The Temperature Modules are connected as shown here:

<figure markdown style="width: 50%;">
![Multiples of a Module](../img/modules/multiples_of_a_module.svg)
</figure>
