# Architecture checklist (phase 1)

What every architecture must answer before the schematic starts. The architect goes
through each item: answered in the spec, not applicable (with the reason), or added to
`open_questions`. Like `phase0_questions.md`, this file improves with every project.

Format: `- **ID** [priority] Item. _Checked by: pipeline rule, or agent judgment._`
Priorities: `must`, `should`, `nice`. IDs are stable; retired items stay, marked `[retired]`.

## Power

- **A-PWR-001** [must] Every rail has min, nominal and max voltage, and the input rail its transients. _Checked by: schema, PWR-004._
- **A-PWR-002** [must] Every rail's worst case load is below its source capacity with margin. _Checked by: PWR-001, PWR-002._
- **A-PWR-003** [must] Every converter's input range and absolute maximum cover its input rail, transients included. _Checked by: RAT-001._
- **A-PWR-004** [must] Every load's supply range covers its rail. _Checked by: RAT-003._
- **A-PWR-005** [must] Input protection is decided: reverse polarity, overvoltage and surge, overcurrent, inrush. _Checked by: agent._
- **A-PWR-006** [should] LDO and linear dissipation fits the package and the ambient temperature. _Checked by: PWR-005 gives the power, agent checks the thermal resistance._
- **A-PWR-007** [should] Sequencing, enables and power-good are defined for parts that need them. _Checked by: agent, from the datasheets._
- **A-PWR-008** [should] Sleep current budget meets the battery life target. _Checked by: agent (pipeline rule planned)._
- **A-PWR-009** [should] Every rail has a test point and a way to measure its current at bring-up. _Checked by: agent._

## Interfaces

- **A-INT-001** [must] Every external connector has a pinout, its levels, its maximum current per pin and its protection (ESD, overvoltage, short to supply). _Checked by: agent._
- **A-INT-002** [must] Connectors that can be swapped or plugged backwards are keyed or survive it. _Checked by: agent._
- **A-INT-003** [should] Hot-plugged connectors have inrush and ESD protection. _Checked by: agent._
- **A-INT-004** [must] Programming and debug access is planned (SWD, UART, boot mode pins reachable). _Checked by: agent._

## Buses and MCU

- **A-BUS-001** [must] Every I2C device has an address, no conflict on a bus. _Checked by: BUS-001, BUS-002._
- **A-BUS-002** [should] I2C pull-ups are sized for the bus capacitance and speed. _Checked by: agent._
- **A-BUS-003** [should] Level translation exists where bus voltages differ. _Checked by: agent._
- **A-MCU-001** [must] Every MCU pin is assigned once and supports its function (alternate function table). _Checked by: MCU-001, agent for the alternate functions._
- **A-MCU-002** [must] Boot and strapping pins have a defined state at reset. _Checked by: agent._
- **A-MCU-003** [should] Outputs that drive actuators have a safe state during reset and firmware crash. _Checked by: agent._
- **A-MCU-004** [nice] Spare pins are left for later features (PRD Q-FUN-005). _Checked by: agent._

## Components

- **A-CMP-001** [must] Every selected part has a datasheet in `datasheets/` and a component sheet. _Checked by: fetch-datasheets, RAT-004._
- **A-CMP-002** [must] Temperature grade of every part covers the operating range. _Checked by: agent (pipeline rule planned)._
- **A-CMP-003** [should] No part is end of life or not recommended for new designs; critical parts have a second source. _Checked by: agent._
- **A-CMP-004** [should] Packages are compatible with the assembler and the height limits. _Checked by: agent._

## Mechanical and manufacturing

- **A-MEC-001** [must] Outline, heights and mounting holes are known, or the open question is listed. _Checked by: agent._
- **A-MEC-002** [should] Stackup and layer count are chosen, with the impedance controlled nets. _Checked by: agent._
- **A-MFG-001** [must] Manufacturer limits are in `design_rules.manufacturer`. _Checked by: agent._
- **A-MFG-002** [should] Net classes cover every power net, sized from its current. _Checked by: agent (rule planned)._

## Compliance and safety

- **A-CMP-101** [must] Mains or hazardous voltages: isolation, creepage and clearance are planned. _Checked by: agent._
- **A-CMP-102** [should] EMC: filtering on external ports, ground strategy, enclosure. _Checked by: agent._

## How this file evolves

- A missed issue traced to the architecture adds an item, with `Added from:` pointing to
  the project and its `review/missed.yaml` entry.
- An item checked by an agent that becomes mechanical gets a pipeline rule, and the
  item names it in `Checked by`.
- The architect proposes changes at the end of each phase 1; the user accepts them by
  pull request.

### Changelog

| Date | Change | Origin |
|---|---|---|
| 2026-11-10 | Initial list | Pipeline design |
