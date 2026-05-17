# Data Quality Agent

## Business Requirements
The purpose of this module is to ingest and assess data quality of a given dataset, in excel format.

### Key Features

#### Data Quality agent realted functionality will be accesses via the Data Quality Assessment option , post the login page

### User Stories

#### US 1.1 Column analysis — Examining individual columns to identify data types, lengths, formats, and value ranges.

#### US 1.2 Null and missing value analysis — Counting empty, null, or blank entries in each column to assess completeness.

#### US 1.3 Uniqueness analysis — Identifying distinct values, duplicates, and candidate primary keys.

#### US 1.4 Value distribution analysis — Looking at frequency of values, min/max, mean, median, mode, and standard deviation for numeric fields.

#### US 1.5 Pattern and format analysis — Detecting common patterns (e.g., phone numbers, emails, dates) and flagging inconsistent formats.

#### US 1.6 Data type validation — Confirming that values match the expected data type (numeric, date, string, boolean, etc.).

#### US 1.7 Range and boundary checks — Verifying values fall within acceptable minimums and maximums.

#### US 1.8 Cross-column (dependency) analysis — Checking relationships and dependencies between columns within the same table (e.g., city should match ZIP code).

#### US 1.9 Cross-table (referential) analysis — Validating foreign key relationships and consistency across related tables.

#### US 2.0 Redundancy detection — Finding repeated or overlapping data across columns or tables.

#### US 2.1 Outlier and anomaly detection — Spotting values that deviate significantly from expected norms.

#### US2.2 The above analysis on a given dataset will be performed by employing a mixed approach i.e. AI Agent based & Statiscal Analysis based. For the AI agent based approach, the user will have an option to configure the model between openai and anthropic , along with model type and api keys.

#### US 2.3 The above analysis will be displayed on a separate page as " Data Quality Dashboard" . The dashboard page will have all types of visual components like bar graphs, pie charts, RAG indicator, tabular components to dispay the calculated and derived dimension values. Research and use the best visual component library to display the output.

#### US 2.4 The dashboard page , will also have a chat interface , enabling the user to interact with the uploaded dataset and answer data quality related questions on the dataset. The chat interface will have a AI agent working behind the scenes with reasoning, thinking and action capabilities. The model for the chat interface agent will have to be configured by the user as part of initial setup.

## Epic 3 - Record Level Similarity Scoring
### US 3.1Post upload of exccel, the application shoudl provide a Profiling Setup & COnfiguration Page.

### US 3.2 Within Profiling Setup & COnfiguration Page, radio buttons to select and deselect various data normalisation and preparation options should be provided:
#### Case normalization — lowercase for comparison, keep original for display
Example: ACME ROBOTICS INC (EX-1042) → acme robotics inc → now matches EX-1001's normalized form

#### Whitespace handling — trim edges, collapse internal multi-spaces
Example: "  Helix Pharmaceuticals  " (EX-1043) → Helix Pharmaceuticals; "Brightlight  Media   LLC" (EX-1044) → Brightlight Media LLC

#### Punctuation stripping — standardize commas, periods, hyphens
Example: Acme Robotics, Inc (EX-1049) → Acme Robotics Inc → matches EX-1001

#### Unicode normalization — NFC/NFKD form, optional accent folding
Example: Café Lumière → Cafe Lumiere for matching, but preserve original for display

#### Special character handling — strip emojis, control chars, zero-width spaces
Example: Café Lumière ☕ → Café Lumière for the comparison key

#### Stop-word / suffix removal — drop corporate suffixes
Example: Acme Robotics Inc, Acme Robotics, Acme Robotics LLC all reduce to acme robotics

#### Abbreviation expansion — for addresses
Example: 120 Market St. → 120 Market Street; 30 St Clair Ave W → 30 Saint Clair Avenue West

#### Field-specific parsers
Example
Phone: (415) 555-0142, 415-555-0142, 4155550142, 415.555.0142 → +14155550142
Email: JAMES.CARTER@ACMEROBOTICS.COM → james.carter@acmerobotics.com
Date: 08/15/2025, 15-Aug-2025, 2025.08.15 → 2025-08-15

### US 3.3 Under profiling setup and configuration page, 
#### -  Field(Column) Importance indicator(radio button) should be there, providing an option to tag a field(column) as important or not
#### -  Window to map weights to column attributes should be there. The limit of weight will vary between 0 and 1 & all decimal values , between 0 an 1 is accepted

### US 3.4 Under profiling setup and configuration page, 

#### - Based on the type of the Field(column) and subsequent data, ai agent will recommend & tag the field level similarity algorithms, that should be mapped to each column such as:
##### -- Exact Match
##### -- Edit-distance (Levenshtein)
##### -- Token-based (Jaccard, Cosine)
##### -- Phonetic (Soundex, Metaphone)
##### -- n-gram similarity
##### -- Numeric tolerance
##### -- Date proximity
##### The user will be able to remove/change the recommended similarity algorithm mapping

### US 3.5 Post configuration , the profiling & similarity scoring excercise will be conducted basis the selections done during at the configuration page

### US 3.6- Similarity Scoring Output
#### Peform grouping  and clustering  of records basis the highest similarity score , for important columns(fields), configured during profiling setup and configuration US 3.3. This should be displayed along with other dq dimensioning metrics , on the dashboard page.