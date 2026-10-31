# Project brief: what Fort Collins households pay to get around, and who gains

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

This brief looks at travel from the household's side. We want to
understand what households in Fort Collins pay to get around, how that
changes in each future, and who gains and who loses. Questions such as:
for which households is an electric vehicle already cheaper to own than
a gasoline one, and when does that cross for the rest? How much does
home-charging access (owners versus renters) change the answer? Does
the Shared future lower costs for carless or low-income households, or
mainly for those who already drive? How would a purchase incentive, a
time-of-use tariff or a transit fare change be shared across income
groups?

## What we want
A working, documented model for Fort Collins, the reporting years and
the three futures, that covers:

- Household groups: by income tercile, tenure (owner or renter, with
  home-charging access), household size or vehicle count, and zone,
  with the population and households by zone they rest on.
- Travel and fleet per household group each year, as the input the
  costs rest on, with the three futures quantified.
- Costs: the total cost of ownership per vehicle by powertrain and
  purchase year (purchase price path, financing, fuel or electricity at
  a stated tariff, maintenance, insurance, resale), the cost of transit
  and cycling, and the cost of a shared service per trip, discounted at
  a stated rate.
- Outcomes: annual mobility spending per household group, by future and
  year; the distribution of gains and losses between futures; and the
  public cost of the levers (incentives, charger subsidies, transit
  fares).

The model's purpose is to show how **purchase incentives and their
targeting**, **tariff design** and **transit fares and service** shape
household costs and their distribution. A user should be able to change
those levers and rerun scenarios.

- Choose the modeling approach yourself and justify it.
- Ground the parameters in published evidence (TCO studies, maintenance
  and insurance costs by powertrain, resale curves, incentive uptake,
  fare elasticities), cite the sources, and mark which are assumptions.
- Sanity-check the baseline against observed figures (household
  transport spending shares from consumer expenditure data, published
  TCO comparisons), and show the check.
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
   results file (`model/results.json`) with costs by household group,
   future and reporting year.
2. A visualization: a single self-contained HTML page with household
   costs by group over time for the futures and a map of gains and
   losses by zone, plus a few static rendered images.
3. A report a technical reader at TRI can use: the question, the scope
   you chose and why, the method, the data and parameters (a table of
   every key input with its value, unit, year and source), the sanity
   checks, the results and their drivers, the uncertainty, and the
   limitations and next steps.
