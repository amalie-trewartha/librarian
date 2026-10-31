# Project brief: electric-vehicle charging and the local grid in Fort Collins, Colorado

## Background
TRI is studying how one small American city's transport and energy
system could change over the next twenty years. The city is Fort
Collins, Colorado (about 170,000 residents), chosen because its data is
open and needs no account: Census ACS and LODES, Transfort's GTFS feed,
OpenStreetMap, Colorado's vehicle registration data and the AFDC station
locator. TRI frames every study in this program around three futures:

- **Baseline**: current policy and trends continue.
- **Electrify**: faster electric-vehicle uptake, a matching public
  charging buildout and purchase incentives.
- **Shared**: a shared automated electric ride-hailing service enters
  around 2032 and carries about 15% of the city's trips by 2040, and the
  household fleet shrinks in response.

Each study quantifies these futures itself from published evidence. The
reporting years are 2030, 2035 and 2045.

This brief asks when and where the city's growing electric-vehicle fleet
charges, and what that does to the local electricity grid, hour by hour
and place by place. We want to understand questions such as: if most
owners charge at home on a time-of-use tariff, does the evening peak
move or grow? How much does managed charging reduce the peak compared
with adding public chargers? Which neighborhoods would see their
service transformers or feeders overloaded first, and in which future?
What does a shared fleet, charged centrally at depots, do to the same
peaks? And can renters, who often cannot charge at home, be served by
public charging without long waits?

## What we want
A working, documented model of EV charging demand and its effect on the
local grid in Fort Collins, for the reporting years and the three
futures, that covers:

- The electric-vehicle fleet and its driving each year, as the input the
  charging demand rests on, from registration data and published travel
  statistics, with the three futures quantified.
- Charging demand over time: when vehicles arrive, how much energy they
  need, and where they charge (home, work, public Level 2, DC fast,
  depots for a shared fleet), at hourly or finer resolution, for a
  typical weekday and weekend in summer and winter.
- The charging network: public chargers by zone and their utilization,
  including queueing or unmet demand when they are scarce.
- The grid: residential and commercial load by zone or feeder with the
  charging load added, and an estimate of where and when local equipment
  would exceed its rating.

The model's purpose is to show how changes in the **availability**
(home-charging access, charger count and placement), **affordability**
(tariff design, charger prices) and **convenience** (dwell and waiting
time, managed charging) of charging affect when and where people charge,
and what the resulting load does to the peak and to local equipment. A
user should be able to change those levers and rerun scenarios.

- Choose the modeling approach yourself (activity-based or agent-based
  charging sessions, queueing, siting optimization, or a combination)
  and justify it.
- Ground the parameters in published evidence where you can (charging
  session data, arrival times and energy per session, response to
  time-of-use prices, managed-charging participation, charger costs and
  utilization, transformer and feeder ratings), cite the sources, and
  mark which parameters are assumptions.
- Calibrate or sanity-check the baseline against observed data for
  comparable places (utility EV load studies, public charging session
  data, AFDC charger counts), and show the check.
- Run the three futures and a set of lever variations, and report what
  drives the peak and local overloads, and where the model is uncertain.

## Scope and planning
You have a fixed timeframe (see the deadline). Decide for yourself what
scope is achievable in that time, write the scope and your plan down
early, and revise them as you learn. A smaller model that runs, is
checked and is honest about its limits is worth more to us than an
ambitious one that is half-built. Record what you left out and why.

## Constraints
- Open data, open literature and open-source software only. If real
  distribution-grid data for the city cannot be obtained without an
  account, build a synthetic grid grounded in published typical ratings
  and say so.
- The model must run from a clean checkout with documented commands, on an
  ordinary Linux machine, without licensed software.
- No secrets or accounts are available to you beyond what you already have.

## Deliverables
1. The model: source code, input data (or scripts that fetch it), one
   command that reruns everything, a README, and a machine-readable
   results file (`model/results.json`) with the load profiles and peaks
   by future and reporting year.
2. A visualization: a single self-contained HTML page with a 24-hour
   play-through of load by zone for at least two futures, plus a few
   static rendered images.
3. A report a technical reader at TRI can use: the question, the scope
   you chose and why, the method, the data and parameters (a table of
   every key input with its value, unit, year and source), the
   calibration, the results and their drivers, the uncertainty, and the
   limitations and next steps.
