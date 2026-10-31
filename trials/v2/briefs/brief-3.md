# Project brief: energy, emissions and air quality of travel in Fort Collins, Colorado

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

This brief asks what the city's travel costs the climate and the people
who breathe the air: the energy use, greenhouse-gas emissions and local
air pollutant emissions of travel in Fort Collins from 2025 to 2045, in
each future, and the monetized damages. We want to understand questions
such as: how much do emissions fall in the Electrify future, and how
much of that depends on how Colorado's grid decarbonizes? Does the
Shared future's empty repositioning driving offset its cleaner vehicles?
Where in the city are pollutant emissions concentrated, and who lives
there? What is the yearly social cost of the remaining emissions?

## What we want
A working, documented model for Fort Collins, the reporting years and
the three futures, that covers:

- Travel and fleet: vehicle-kilometers by mode and the light-duty fleet
  by powertrain and vintage each year, as the inputs the emissions rest
  on, from registration data and published travel statistics, with the
  three futures quantified.
- Energy: fuel and electricity used by the fleet each year, by
  powertrain and vintage, including the charging energy of electric
  vehicles.
- Greenhouse gases: well-to-wheel emissions, with an electricity
  emission factor path for Colorado to 2045 (hourly or at least seasonal
  where charging timing makes it matter) and the upstream emissions of
  fuels and of vehicle and battery manufacturing.
- Air pollutants: tailpipe and non-exhaust (brake and tire) NOx and
  particulate emissions by zone, by vehicle vintage and emission
  standard.
- Damages: the social cost of the greenhouse gases and the health
  damages of the pollutants, with the population exposed by zone, using
  a stated discount rate.

The model's purpose is to show how **grid decarbonization**, **fleet
turnover** and **travel demand** shape emissions and damages. A user
should be able to change those levers and rerun scenarios.

- Choose the modeling approach yourself and justify it.
- Ground the parameters in published evidence (grid emission factors
  and their projections, fuel upstream factors, vehicle and battery
  manufacturing emissions, emission standards and deterioration, damage
  costs per tonne), cite the sources, and mark which are assumptions.
- Sanity-check the baseline against published figures (per-capita
  transport emissions for comparable cities, Colorado's inventory), and
  show the check.
- Run the three futures and a few lever variations, and report what
  drives the results and where the model is uncertain.

## Scope and planning
You have a fixed timeframe (see the deadline). Decide for yourself what
scope is achievable in that time, write the scope and your plan down
early, and revise them as you learn. A smaller model that runs, is
checked and is honest about its limits is worth more to us than an
ambitious one that is half-built. Record what you left out and why.

## Constraints
- Open data, open literature and open-source software only.
- The model must run from a clean checkout with documented commands, on an
  ordinary Linux machine, without licensed software.
- No secrets or accounts are available to you beyond what you already have.

## Deliverables
1. The model: source code, input data (or scripts that fetch it), one
   command that reruns everything, a README, and a machine-readable
   results file (`model/results.json`) with energy, emissions and
   damages by future and reporting year.
2. A visualization: a single self-contained HTML page with emissions
   over time by future and a zone map of pollutant emissions or
   exposure, plus a few static rendered images.
3. A report a technical reader at TRI can use: the question, the scope
   you chose and why, the method, the data and parameters (a table of
   every key input with its value, unit, year and source), the sanity
   checks, the results and their drivers, the uncertainty, and the
   limitations and next steps.
