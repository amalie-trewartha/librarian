# Project brief: a transport and energy policy package for the Fort Collins city council

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

The city council has asked TRI what it should do. This brief asks for
two or three policy packages, each a bundle of levers (purchase
incentives and their targeting, a public charging buildout, managed
charging or a time-of-use tariff, transit service or fare changes,
terms for a shared automated service), evaluated on one scorecard that
covers travel, the grid, emissions and health, and household costs. A
council will act on a package only if the numbers behind it hang
together: the fleet that produces the emissions must be the fleet that
charges and the fleet the households pay for.

## What we want
1. **A scorecard** for the three futures and for each policy package, in
   2030, 2035 and 2045: vehicle-kilometers and mode shares; peak
   electricity load from charging and the equipment it strains;
   greenhouse-gas and pollutant emissions and their monetized damages;
   household mobility costs by income tercile and the public cost of the
   package; and a net present value of costs and benefits at a stated
   discount rate with a stated social cost of carbon. Every number on
   the scorecard is produced by a model you can rerun, from one set of
   inputs, never retyped.
2. **Two or three policy packages**, each defined as a set of lever
   settings, with a short rationale, its scorecard row, and the main
   uncertainty that could change its rank.
3. **An inputs register**: every quantity the scorecard rests on
   (population and households by zone; the fleet by powertrain in each
   reporting year and future; vehicle-kilometers by mode; energy and
   vehicle price paths; the electricity tariff; the charging profile;
   the grid emission factor; the discount rate; the social cost of
   carbon; the three futures' defining numbers), each with its value,
   unit, year and source, and the parts of the scorecard that use it.

The model's purpose is to compare packages on one consistent basis, so a
simple model whose parts agree is worth more than detailed parts that
disagree. A user should be able to change a package's levers and rerun
the scorecard.

- Choose the modeling approach yourself (a chain of simple models over
  one shared input set is expected) and justify it.
- Ground the parameters in published evidence, cite the sources, and
  mark which are assumptions.
- Sanity-check the baseline scorecard against published figures where
  they exist (per-capita emissions, household transport spending,
  registrations by powertrain), and show the check.
- Report what drives each package's rank and where the ranking is
  uncertain.

## Scope and planning
You have a fixed timeframe (see the deadline). Decide for yourself what
scope is achievable in that time, write the scope and your plan down
early, and revise them as you learn. A smaller scorecard whose inputs
agree is worth more to us than a long one that is half-built or
inconsistent. Record what you left out and why.

## Constraints
- Open data, open literature and open-source software only.
- The model must run from a clean checkout with documented commands, on an
  ordinary Linux machine, without licensed software.
- No secrets or accounts are available to you beyond what you already have.

## Deliverables
1. The model: source code, input data (or scripts that fetch it), one
   command that reruns everything, a README, and `model/scorecard.json`
   plus `model/inputs.json` (the register) by future, package and
   reporting year.
2. A visualization: a single self-contained HTML page showing the
   scorecard and the packages side by side, plus a few static rendered
   images.
3. A report for the city council and a technical reader at TRI: the
   question, the packages and why these, the scorecard and what drives
   it, the inputs register, the uncertainty, and what TRI would do next.
