# Phase 0 questions

The list of questions and data the interviewer agent needs to write a good PRD.
It is shared across all projects and improves with every use (see "How this file evolves").

Format of each entry:

`- **ID** [priority] Question. _Drives: what this answer is used for._`

Priorities:
- `must`: the architecture cannot be done without it. If unknown, record an explicit
  assumption and list it as an open question.
- `should`: asked when relevant for this product.
- `nice`: asked only if time allows or the documents hint at it.

IDs are stable: never reuse or renumber an ID, mark removed questions as `[retired]`.

## 1. Product and context

- **Q-PRD-001** [must] What does the board do, in one or two sentences? _Drives: block diagram._
- **Q-PRD-002** [must] Is it a standalone product, a module inside a larger system, or a test or lab board? _Drives: robustness level, connectors, compliance._
- **Q-PRD-003** [must] How many units: prototypes only, small series, production volume per year? _Drives: part selection, assembly method, cost trade-offs._
- **Q-PRD-004** [should] Target unit cost (BOM and assembled board)? _Drives: component selection, layer count._
- **Q-PRD-005** [should] Deadline for the first prototype and for production? _Drives: part availability, lead times, risk taken._
- **Q-PRD-006** [should] Is there a previous version or a reference design? What was wrong with it? _Drives: reuse, known pitfalls._
- **Q-PRD-007** [nice] Who uses the product and how (end user, technician, lab)? _Drives: user interface, protection against misuse._

## 2. Functions and performance

- **Q-FUN-001** [must] List of functions, each with its performance target (accuracy, speed, range, resolution). _Drives: blocks and key parts._
- **Q-FUN-002** [must] Operating modes (off, sleep, idle, active, fault) and what happens in each. _Drives: power budget, sequencing._
- **Q-FUN-003** [should] Signals measured or generated: type, range, bandwidth, accuracy. _Drives: ADC, DAC, analog front end, references._
- **Q-FUN-004** [should] Timing constraints: latency, synchronization, real-time clock, timestamps. _Drives: MCU choice, clocks, RTC._
- **Q-FUN-005** [nice] Features planned for later versions that the board should already allow? _Drives: spare pins, footprints for optional parts._

## 3. Power

- **Q-PWR-001** [must] Power sources: battery (chemistry, cells), adapter, USB (which power level, PD?), PoE, vehicle 12 or 24 V, mains? _Drives: input stage, power tree._
- **Q-PWR-002** [must] Input voltage range, including transients (load dump, cold crank, hot plug surge). _Drives: regulator ratings, TVS, capacitor ratings._
- **Q-PWR-003** [must] Power or current budget per mode, peak and average. _Drives: regulators, connectors, track widths, thermal._
- **Q-PWR-004** [must] Protection required: reverse polarity, overvoltage, overcurrent, short circuit on outputs. _Drives: input protection, eFuses._
- **Q-PWR-005** [should] Battery life target and sleep current target. _Drives: regulator quiescent current, power gating._
- **Q-PWR-006** [should] Charging: chemistry, charge current, charging while operating, temperature limits. _Drives: charger IC, NTC._
- **Q-PWR-007** [should] Power provided to external devices (sensors, actuators, other boards): voltage, current, protection. _Drives: output rails, current limits._
- **Q-PWR-008** [should] Power up and power down sequencing constraints, brownout behavior. _Drives: supervisors, enables, power-good._
- **Q-PWR-009** [nice] Hold-up time needed on power loss (save data, safe shutdown)? _Drives: bulk capacitance, supercap._

## 4. External interfaces and connectors

- **Q-INT-001** [must] Every external connection: what it connects to, signals, voltage levels, protocol. _Drives: connectors, transceivers, protection._
- **Q-INT-002** [must] Imposed connectors (part numbers, standards) or free choice? _Drives: mechanical, pinout._
- **Q-INT-003** [should] Cable lengths and environment (shielded, near motors, outdoors). _Drives: ESD, EMC filtering, transceiver choice._
- **Q-INT-004** [should] Can the user plug or unplug while powered? Can connectors be swapped or plugged backwards? _Drives: hot-plug protection, keying._
- **Q-INT-005** [should] User interface: buttons, LEDs, display, buzzer. _Drives: GPIO count, front panel layout._
- **Q-INT-006** [must] Programming and debug access: SWD or JTAG, UART console, USB DFU, test pads or connector? _Drives: debug connector, boot strapping._
- **Q-INT-007** [should] Harness: who makes it, wire gauge, pinout already defined? _Drives: connector pinout, current per pin._

## 5. Processing, buses and wireless

- **Q-PRC-001** [must] MCU or processor imposed, preferred family, or free choice? Existing firmware or toolchain to keep? _Drives: MCU selection._
- **Q-PRC-002** [should] Memory needs: flash, RAM, external storage, logging. _Drives: MCU, external flash, SD card._
- **Q-PRC-003** [should] Devices on shared buses (I2C, SPI, CAN, RS-485): list, and fixed addresses if known. _Drives: I2C address map, bus count, pull-ups._
- **Q-PRC-004** [should] Wireless: which (BLE, Wi-Fi, LoRa, cellular, GNSS), module or chip-down, antenna internal or external? _Drives: RF layout, certification, keep-outs._
- **Q-PRC-005** [nice] Security needs: secure boot, encrypted storage, secure element? _Drives: MCU features, extra parts._

## 6. Mechanical

- **Q-MEC-001** [must] Board outline and size limits, or enclosure to fit in. _Drives: placement, layer count._
- **Q-MEC-002** [must] Maximum component height on each side. _Drives: part packages, connectors, capacitors._
- **Q-MEC-003** [should] Mounting holes, positions, grounded or isolated. _Drives: outline, grounding strategy._
- **Q-MEC-004** [should] Imposed positions of connectors, buttons, LEDs, antennas. _Drives: placement._
- **Q-MEC-005** [should] Enclosure material (metal, plastic) and how heat leaves the board. _Drives: thermal design, RF, grounding._
- **Q-MEC-006** [nice] Is there a mechanical CAD model (Onshape) to align with? _Drives: phase 3 checks._

## 7. Environment

- **Q-ENV-001** [must] Operating and storage temperature range. _Drives: part grades, derating, capacitor dielectrics._
- **Q-ENV-002** [should] Humidity, condensation, dust, water (IP rating), conformal coating? _Drives: clearances, coating keep-outs._
- **Q-ENV-003** [should] Vibration and shock. _Drives: heavy parts, connector retention, large capacitors._
- **Q-ENV-004** [should] Expected lifetime and duty cycle. _Drives: electrolytic capacitor life, flash endurance, derating._
- **Q-ENV-005** [nice] Altitude, UV, chemicals. _Drives: clearances, materials._

## 8. Standards and compliance

- **Q-CMP-001** [must] Target markets (EU, US, other) and required marks (CE, FCC, UKCA, UL). _Drives: EMC design, safety, certification budget._
- **Q-CMP-002** [should] Product standards that apply (industrial, automotive AEC-Q, medical, railway). _Drives: part grades, test levels._
- **Q-CMP-003** [must] Mains or hazardous voltages on the board? Isolation class needed? _Drives: creepage, clearance, isolation parts._
- **Q-CMP-004** [should] ESD and surge levels required on external ports (IEC 61000-4-2, 4-5). _Drives: TVS, layout of protection._
- **Q-CMP-005** [nice] RoHS, REACH, conflict minerals, other material constraints. _Drives: part selection._

## 9. Manufacturing and test

- **Q-MFG-001** [must] Who makes and assembles the board (JLCPCB, PCBWay, local assembler, in-house)? _Drives: design rules, part library constraints._
- **Q-MFG-002** [should] Layer count budget, board thickness, copper weight, minimum track and space allowed. _Drives: design rules, stackup._
- **Q-MFG-003** [should] Assembly constraints: single or double sided, hand soldered parts, preferred or basic parts list. _Drives: package choice, placement._
- **Q-MFG-004** [should] Preferred distributors, parts to reuse, forbidden parts or manufacturers. _Drives: component selection._
- **Q-MFG-005** [should] Production test: test points, bed of nails, programming fixture, functional test harness. _Drives: test points, connectors._
- **Q-MFG-006** [nice] Panelization and depanelization constraints. _Drives: outline, edge clearance._

## 10. Reliability and safe behavior

- **Q-REL-001** [should] What must happen on a fault (power loss, firmware crash, sensor failure)? Safe states of outputs? _Drives: default pull states, watchdog, supervisors._
- **Q-REL-002** [should] Single points of failure that are not acceptable? _Drives: redundancy, protection._
- **Q-REL-003** [nice] Field diagnostics needed (status LEDs, logs, remote update)? _Drives: UI, memory, connectivity._

## 11. Deliverables

- **Q-DLV-001** [should] What must be delivered: KiCad files, Gerbers, BOM, assembly drawings, test report? _Drives: phase outputs._
- **Q-DLV-002** [nice] Naming, revision and documentation conventions to follow. _Drives: project template._

## How this file evolves

The pipeline adds, rewrites or retires questions from real use:

- **A missed issue traced back to a missing answer** (for example a connector that could
  be plugged backwards, found at bring-up) adds a question, with `Added from:` pointing to
  the project and the entry in `review/missed.yaml`.
- **A question the user always answers the same way** becomes a default in the
  user's profile below, and is only asked to confirm.
- **A question that never changes the design** is lowered to `nice` or retired.
- **At the end of each phase 0**, the interviewer proposes changes to this file. The
  user accepts them through a pull request, like any other pipeline change.

### User defaults

Answers that are usually true for this user's projects. The interviewer states them as
assumptions and asks for confirmation instead of asking from scratch.

_None yet._

### Changelog

| Date | Change | Origin |
|---|---|---|
| 2026-11-10 | Initial list | Pipeline design |
