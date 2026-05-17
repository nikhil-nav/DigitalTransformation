# The CRM MVP web app

## Business Requirements

This project is building a Digital Transformation Platform. 


### Key Features

##### Should have a login Page
##### Should be able to create a New Project or Open existing Project
##### For every Project there will be multiple project types supported
##### For MVP "Value Disovery" will be Active Project Type
##### Other Inactive Project Types will be Business Process Discovery, AI Assessment, Data Quality Assessment 


## Limitations

For the MVP, there will only be a user sign in (hardcoded to 'user' and 'password') but the database will support multiple users for future.

For the MVP, this will run locally (in a docker container)

## Technical Decisions

- NextJS frontend
- Python FastAPI backend; Next.js runs as a separate Node process, FastAPI serves the API at /api
- Two separate Docker containers (frontend + backend) managed by docker compose
- Use "uv" as the package manager for python in the Docker container
- Use SQLLite local database for the database, creating a new db if it doesn't exist
- Start and Stop server scripts for Mac, PC, Linux in scripts/


## Color Scheme

-Coral Primary: #FF7A59 - main CTA buttons, key actions, brand accent
-Pickled Bluewood: #33475B - main headings, navigation background, logo
-Deep Bluewood: #2D3E50 - sidebar, nav background, dark surfaces
-Cerulean: #0091AE - links, interactive elements, info states
-Jade: #00BDA5 - success states, Closed Won stage, positive indicators
-Marigold: #F5C26B - warnings, alerts, Proposal stage highlight
-Watermelon: #F2545B - errors, danger states, Closed Lost stage
-Slate: #516F90 - muted text, secondary labels, supporting copy
-Heather: #7C98B6 - placeholder text, hints, inactive elements
-Fog: #EAF0F6 - page backgrounds, table row fills
-Geyser: #DFE3EB - borders, dividers, card outlines
-Forget Me Not: #FFF1EE - coral tint background, hero sections, empty states

## Fonts and Themes
-Use Enterprise theme

## Coding standards

1. Use latest versions of libraries and idiomatic approaches as of today
2. Keep it simple - NEVER over-engineer, ALWAYS simplify, NO unnecessary defensive programming. No extra features - focus on simplicity.
3. Be concise. Keep README minimal. IMPORTANT: no emojis ever
4. When hitting issues, always identify root cause before trying a fix. Do not guess. Prove with evidence, then fix the root cause.

## Working documentation

All documents for planning and executing this project will be in the docs/ directory.
Please review the docs/PLAN.md document before proceeding.

---

