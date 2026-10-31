# Project brief: the vehicle fleet and travel of Fort Collins, Colorado, 2025 to 2045

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

This brief asks how the city's light-duty vehicle fleet turns over, how
much and by which modes people travel, and how both change in the three
futures. We want to understand questions such as: what happens to
battery-electric uptake if public charging doubles or purchase prices
fall? Does better cycling infrastructure take trips mainly from cars or
from transit? How much driving does the Shared future remove or add?

## What we want
A working, documented model of Fort Collins that covers, for each year
from 2025 to 2045:

- The light-duty vehicle fleet by powertrain (battery-electric, plug-in
  hybrid, hybrid, internal combustion) and by model-year vintage:
  ownership per household, purchases, survival and scrappage, and the
  stock each year. Model the turnover, not just new sales.
- Travel: trips and vehicle-kilometers by mode (car, transit, cycling
  including e-bikes, walking) for a typical weekday, by zone, with the
  population and households by zone they rest on.
- The three futures, each with its defining assumptions (adoption
  paths, price paths, service entry and share) written down as numbers
  with sources.

The model's purpose is to show how changes in the **availability**,
**affordability** and **convenience** of each option affect the fleet
mix, mode shares and travel over time. A user should be able to change
those levers and rerun scenarios.

- Choose the modeling approach yourself (for example discrete choice
  with a stock-turnover model, or a combination) and justify it.
- Ground the parameters in published evidence where you can (vehicle
  survival, purchase elasticities, value of time, cost of ownership,
  mode-choice coefficients), cite the sources, and mark which parameters
  are assumptions.
- Calibrate or sanity-check the baseline against observed data for the
  city or comparable cities (registrations by powertrain, commute mode
  shares, vehicle-miles), and show the check.
- Run the three futures and a set of lever variations, and report what
  drives the results and where the model is uncertain.

## Scope and planning
You have a fixed timeframe (see the deadline). Decide for yourself what
scope is achievable in that time, write the scope and your plan down
early, and revise them as you learn. A smaller model that runs, is
calibrated and is honest about its limits is worth more to us than an
ambitious one that is half-built. Record what you left out and why.

## Constraints
- Open data, open literature and open-source software only.
- The model must run from a clean checkout with documented commands, on an
  ordinary Linux machine, without licensed software.
- No secrets or accounts are available to you beyond what you already have.

## Deliverables
1. The model: source code, input data (or scripts that fetch it), one
   command that reruns everything, a README, and a machine-readable
   results file (`model/results.json`) with the headline numbers by
   future and reporting year.
2. A visualization: a single self-contained HTML page (no server, no
   account) with the fleet mix, mode shares and vehicle-kilometers over
   time for the three futures, and a map of the zones with one result
   on it. Also provide a few static rendered images.
3. A report a technical reader at TRI can use: the question, the scope
   you chose and why, the method, the data and parameters (a table of
   every key input with its value, unit, year and source), the
   calibration, the results and their drivers, the uncertainty, and the
   limitations and next steps.
