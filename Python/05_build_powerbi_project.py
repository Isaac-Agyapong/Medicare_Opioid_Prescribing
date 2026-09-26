"""
Generate the Power BI Project (PBIP) for the dashboard. The model imports the `analytics` views
directly from PostgreSQL (server and database are parameters), so Refresh re-reads the database.

    dashboard/Opioid_Prescribing.pbip                open this in Power BI Desktop
    dashboard/Opioid_Prescribing.SemanticModel/      model (TMDL), columns read from the database
    dashboard/Opioid_Prescribing.Report/             3 report pages (PBIR JSON)

Re-running replaces the dashboard folder (including Power BI's saved data cache): open the
.pbip afterwards and click Refresh.
"""
import importlib
import json
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parents[1]
DASH = ROOT / "dashboard"
NAME = "Opioid_Prescribing"
SM = DASH / f"{NAME}.SemanticModel"
RPT = DASH / f"{NAME}.Report"
CONNINFO = importlib.import_module("02_load_postgres").CONNINFO

VIEWS = ["national_trend", "state_year", "specialty_year", "rural_urban_trend", "outlier_summary"]
HIDDEN = {"year", "state_fips", "prescribing_rank"}

SCHEMA = "https://developer.microsoft.com/json-schemas/fabric"
S_PBIP = f"{SCHEMA}/pbip/pbipProperties/1.0.0/schema.json"
S_PBISM = f"{SCHEMA}/item/semanticModel/definitionProperties/1.0.0/schema.json"
S_PBIR = f"{SCHEMA}/item/report/definitionProperties/2.0.0/schema.json"
S_VERSION = f"{SCHEMA}/item/report/definition/versionMetadata/1.0.0/schema.json"
S_REPORT = f"{SCHEMA}/item/report/definition/report/1.2.0/schema.json"
S_PAGES = f"{SCHEMA}/item/report/definition/pagesMetadata/1.0.0/schema.json"
S_PAGE = f"{SCHEMA}/item/report/definition/page/1.3.0/schema.json"
S_VISUAL = f"{SCHEMA}/item/report/definition/visualContainer/1.4.0/schema.json"

BASE_THEME = "CY24SU10"
CUSTOM_THEME = "OpioidPortfolioTheme.json"
BLUE, ORANGE, AQUA, GREY = "#2A78D6", "#EB6834", "#1BAF7A", "#C3C2B7"
PCT1, PCT2, INT = "0.0%;-0.0%;0.0%", "0.00%;-0.00%;0.00%", "#,0"
TYPE_MAP = {"smallint": "int64", "integer": "int64", "bigint": "int64", "numeric": "double",
            "text": "string", "character": "string", "character varying": "string"}


def find_base_theme():
    """The base theme ships with Power BI Desktop (Microsoft Store install)."""
    # WindowsApps can't be listed, so ask Windows for the install folder
    install = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "(Get-AppxPackage Microsoft.MicrosoftPowerBIDesktop | Sort-Object Version | Select-Object -Last 1).InstallLocation"],
        capture_output=True, text=True).stdout.strip()
    f = Path(install) / "bin/WebView2Resources/minerva/sharedresources/BaseThemes" / f"{BASE_THEME}.json"
    if install and f.exists():
        return f
    raise FileNotFoundError("Power BI Desktop (Microsoft Store version) base theme not found")


def tag(*parts):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "opioid/" + "/".join(parts)))


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def write_json(path, obj):
    write(path, json.dumps(obj, indent=2) + "\n")


def q(name):
    return name if name.replace("_", "").isalnum() else "'" + name.replace("'", "''") + "'"


def indent(text, tabs):
    return "\n".join("\t" * tabs + line if line else "" for line in text.splitlines())


# =====================================================================
# Measures: (home table, name, DAX, format, folder)
# =====================================================================
LATEST = "DimYear[Year] = MAX ( DimYear[Year] )"
MEASURES = [
    ("national_trend", "Opioid Rate",
     "DIVIDE ( SUM ( national_trend[opioid_claims] ), SUM ( national_trend[total_claims] ) )", PCT2, "National"),
    ("national_trend", "Opioid Claims", "SUM ( national_trend[opioid_claims] )", INT, "National"),
    ("national_trend", "Latest Opioid Rate", f"CALCULATE ( [Opioid Rate], {LATEST} )", PCT2, "National"),
    ("national_trend", "Rate Change Since 2013",
     "VAR _now = [Latest Opioid Rate]\nVAR _base = CALCULATE ( [Opioid Rate], DimYear[Year] = 2013 )\n"
     "RETURN DIVIDE ( _now - _base, _base )", PCT1, "National"),
    ("national_trend", "Opioid Deaths", "SUM ( national_trend[opioid_deaths] )", INT, "National"),
    ("national_trend", "Synthetic Opioid Deaths", "SUM ( national_trend[synthetic_opioid_deaths] )", INT, "National"),
    ("national_trend", "Rx Opioid Deaths", "SUM ( national_trend[rx_opioid_deaths] )", INT, "National"),
    ("national_trend", "Heroin Deaths", "SUM ( national_trend[heroin_deaths] )", INT, "National"),
    ("national_trend", "Latest Opioid Deaths", f"CALCULATE ( [Opioid Deaths], {LATEST} )", INT, "National"),
    ("national_trend", "Peak Opioid Deaths",
     "MAXX ( ALL ( DimYear[Year] ), [Opioid Deaths] )", INT, "National"),
    ("national_trend", "Synthetic Share",
     "DIVIDE ( [Synthetic Opioid Deaths], [Opioid Deaths] )", PCT1, "National"),
    ("national_trend", "Latest Synthetic Share", f"CALCULATE ( [Synthetic Share], {LATEST} )", PCT1, "National"),

    ("state_year", "State Opioid Rate",
     "DIVIDE ( SUM ( state_year[opioid_claims] ), SUM ( state_year[total_claims] ) )", PCT2, "States"),
    ("state_year", "Overdose Death Rate",
     "// deaths per 100,000, pooled over the selected years that have death data\n"
     "DIVIDE ( SUM ( state_year[all_drug_deaths] ),\n"
     "    SUMX ( state_year, IF ( NOT ISBLANK ( state_year[all_drug_deaths] ), state_year[population] ) ) ) * 100000",
     "0.0", "States"),
    ("state_year", "Fentanyl Death Rate",
     "DIVIDE ( SUM ( state_year[synthetic_opioid_deaths] ),\n"
     "    SUMX ( state_year, IF ( NOT ISBLANK ( state_year[synthetic_opioid_deaths] ), state_year[population] ) ) ) * 100000",
     "0.0", "States"),
    ("state_year", "Rx Opioid Death Rate",
     "DIVIDE ( SUM ( state_year[rx_opioid_deaths] ),\n"
     "    SUMX ( state_year, IF ( NOT ISBLANK ( state_year[rx_opioid_deaths] ), state_year[population] ) ) ) * 100000",
     "0.0", "States"),

    ("specialty_year", "Specialty Opioid Claims", "SUM ( specialty_year[opioid_claims] )", INT, "Prescribers"),
    ("specialty_year", "Share of Opioid Claims",
     "DIVIDE ( [Specialty Opioid Claims],\n"
     "    CALCULATE ( [Specialty Opioid Claims],\n        REMOVEFILTERS ( specialty_year[specialty_group], specialty_year[Prescriber Group] ) ) )", PCT1, "Prescribers"),
    ("specialty_year", "Specialty Opioid Rate",
     "DIVIDE ( SUM ( specialty_year[opioid_claims] ), SUM ( specialty_year[total_claims] ) )", PCT1, "Prescribers"),
    ("specialty_year", "NP / PA Share",
     'CALCULATE ( [Share of Opioid Claims], specialty_year[specialty_group] = "Nurse Practitioner / PA" )', PCT1, "Prescribers"),
    ("specialty_year", "Primary Care Share",
     'CALCULATE ( [Share of Opioid Claims], specialty_year[specialty_group] = "Primary Care" )', PCT1, "Prescribers"),

    ("outlier_summary", "High Outliers",
     f"// outliers are counted per year, so show the latest selected year rather than a multi-year sum\nCALCULATE ( SUM ( outlier_summary[high_outliers] ), {LATEST} )", INT, "Outliers"),
    ("outlier_summary", "Eligible Prescribers",
     f"CALCULATE ( SUM ( outlier_summary[eligible_prescribers] ), {LATEST} )", INT, "Outliers"),
    ("outlier_summary", "Outlier Share of Claims",
     f"CALCULATE ( DIVIDE ( SUM ( outlier_summary[outlier_opioid_claims] ), SUM ( outlier_summary[opioid_claims] ) ), {LATEST} )",
     PCT1, "Outliers"),

    ("rural_urban_trend", "Rural Opioid Rate",
     'CALCULATE ( AVERAGE ( rural_urban_trend[opioid_rate] ), rural_urban_trend[area] = "Rural" ) / 100', PCT2, "Rural"),
    ("rural_urban_trend", "Urban Opioid Rate",
     'CALCULATE ( AVERAGE ( rural_urban_trend[opioid_rate] ), rural_urban_trend[area] = "Urban" ) / 100', PCT2, "Rural"),

    # --- text measures: the context line under each KPI and the state tooltip
    ("national_trend", "Peak Year",
     "MAXX ( TOPN ( 1, ALL ( DimYear[Year] ), [Opioid Deaths], DESC ), DimYear[Year] )", "0", "Context"),
    ("national_trend", "KPI Rate Context",
     '"in " & MAX ( DimYear[Year] ) & "  ·  was "\n'
     '    & FORMAT ( CALCULATE ( [Opioid Rate], DimYear[Year] = 2013 ), "0.00%" ) & " in 2013"', None, "Context"),
    ("national_trend", "KPI Change Context",
     '"vs. 2013  ·  lower every year"', None, "Context"),
    ("national_trend", "KPI Peak Context",
     '"in " & [Peak Year] & "  ·  " & FORMAT ( [Latest Opioid Deaths], "#,0" ) & " in " & MAX ( DimYear[Year] )',
     None, "Context"),
    ("national_trend", "KPI Synthetic Context",
     '"in " & MAX ( DimYear[Year] ) & "  ·  "\n'
     '    & FORMAT ( CALCULATE ( [Synthetic Share], DimYear[Year] = 2015 ), "0%" ) & " in 2015"', None, "Context"),
    ("state_year", "Selected State", 'SELECTEDVALUE ( state_year[state_name], "All states" )', None, "Context"),
    ("state_year", "Prescribing Rank Text",
     "VAR _rank = RANKX ( ALL ( StateGrid[state_abbr] ), CALCULATE ( [State Opioid Rate], REMOVEFILTERS ( state_year[state_name] ), REMOVEFILTERS ( state_year[state_abbr] ) ) )\n"
     'RETURN IF ( HASONEVALUE ( StateGrid[state_abbr] ), "Prescribing rank: #" & _rank & " of 51" )', None, "Context"),

    # --- executive visuals
    ("national_trend", "Fentanyl-Involved Deaths", "[Synthetic Opioid Deaths]", INT, "National"),
    ("national_trend", "Other Opioid Deaths",
     "// opioid deaths not involving synthetic opioids: stacks with the line above without double counting\n"
     "[Opioid Deaths] - [Synthetic Opioid Deaths]", INT, "National"),
    ("state_year", "Top 10 Prescribing Rate",
     "VAR _rank = RANKX ( ALLSELECTED ( state_year[state_name] ), [State Opioid Rate] )\n"
     "RETURN IF ( _rank <= 10, [State Opioid Rate] )", PCT2, "States"),
    ("state_year", "Top 10 Death Rate",
     "VAR _rank = RANKX ( ALLSELECTED ( state_year[state_name] ), [Overdose Death Rate] )\n"
     "RETURN IF ( _rank <= 10, [Overdose Death Rate] )", "0.0", "States"),
    ("national_trend", "Latest Fentanyl-Involved Deaths", f"CALCULATE ( [Fentanyl-Involved Deaths], {LATEST} )",
     INT, "National"),
    ("national_trend", "Latest Other Opioid Deaths", f"CALCULATE ( [Other Opioid Deaths], {LATEST} )", INT, "National"),
    ("national_trend", "KPI Deaths Context",
     '"down " & FORMAT ( 1 - DIVIDE ( [Latest Opioid Deaths], [Peak Opioid Deaths] ), "0%" )\n'
     '    & " from the " & [Peak Year] & " peak"', None, "Context"),
    ("state_year", "Death State Prescribing Rate",
     "IF ( NOT ISBLANK ( [Top 10 Death Rate] ), [State Opioid Rate] )", PCT2, "States"),
    ("state_year", "Death State Prescribing Rank",
     "// rank among all 51 states for the selected year, whatever state filters are active\n"
     "VAR _cur = [State Opioid Rate]\n"
     "VAR _all = CALCULATETABLE (\n"
     '    ADDCOLUMNS ( VALUES ( state_year[state_name] ), "@rate", [State Opioid Rate] ),\n'
     "    REMOVEFILTERS ( StateGrid ), REMOVEFILTERS ( state_year[state_name] ), REMOVEFILTERS ( state_year[state_abbr] ) )\n"
     "RETURN IF ( NOT ISBLANK ( [Top 10 Death Rate] ), COUNTROWS ( FILTER ( _all, [@rate] > _cur ) ) + 1 )",
     r"\#0", "States"),
    ("specialty_year", "Share Change 2019-2024",
     "// percentage-point change in each group's share of opioid prescriptions (waterfall)\n"
     "( CALCULATE ( [Share of Opioid Claims], DimYear[Year] = 2024 )\n"
     "    - CALCULATE ( [Share of Opioid Claims], DimYear[Year] = 2019 ) ) * 100",
     "+0.0\" pts\";-0.0\" pts\";0.0\" pts\"", "Prescribers"),
    ("specialty_year", "Share (Slope)",
     "// slope chart: only the first and last year, so each group becomes one line from 2019 to 2024\n"
     "IF ( MAX ( DimYear[Year] ) IN { 2019, 2024 }, [Share of Opioid Claims] )", PCT1, "Prescribers"),
    ("specialty_year", "Share 2019", "CALCULATE ( [Share of Opioid Claims], DimYear[Year] = 2019 )", PCT1, "Prescribers"),
    ("specialty_year", "Share 2024", "CALCULATE ( [Share of Opioid Claims], DimYear[Year] = 2024 )", PCT1, "Prescribers"),
    ("outlier_summary", "Outlier Share of Prescribers",
     "DIVIDE ( [High Outliers], [Eligible Prescribers] )", "0.0%;-0.0%;0.0%", "Outliers"),

    # --- tile-grid map: each state is a marker at a fixed grid position, coloured by death rate
    ("state_year", "Tile X", "MIN ( StateGrid[tile_x] )", "0", "Map"),
    # rows are spaced 1.45 units apart so each state label fits under its tile
    ("state_year", "Tile Y", "-1.45 * MIN ( StateGrid[tile_y] )", "0.0", "Map"),
    ("state_year", "Tile Size", "IF ( NOT ISEMPTY ( StateGrid ), 1 )", "0", "Map"),
    ("state_year", "Tile Label", "SELECTEDVALUE ( StateGrid[state_abbr] )", None, "Map"),
    ("state_year", "Tile Label Colour",
     "VAR _r = [Overdose Death Rate]\nRETURN IF ( NOT ISBLANK ( _r ) && _r >= 40, \"#FFFFFF\", \"#0B0B0B\" )", None, "Map"),
    ("state_year", "Death Rate Colour",
     "VAR _r = [Overdose Death Rate]\n"
     "RETURN SWITCH ( TRUE (),\n"
     '    ISBLANK ( SELECTEDVALUE ( StateGrid[state_abbr] ) ), "#FFFFFF",\n'
     '    ISBLANK ( _r ), "#E1E4EA",\n'
     '    _r < 20, "#FBE3D6",\n'
     '    _r < 30, "#F5B48F",\n'
     '    _r < 40, "#EE8452",\n'
     '    _r < 50, "#D95926",\n'
     '    "#9E3A12" )', None, "Map"),
]

# Tile-grid positions (column, row) for the 50 states + DC, arranged like a US map
STATE_GRID = {
    "AK": (0, 0), "ME": (10, 0),
    "WI": (5, 1), "VT": (9, 1), "NH": (10, 1),
    "WA": (0, 2), "ID": (1, 2), "MT": (2, 2), "ND": (3, 2), "MN": (4, 2), "IL": (5, 2), "MI": (6, 2),
    "NY": (8, 2), "MA": (9, 2),
    "OR": (0, 3), "NV": (1, 3), "WY": (2, 3), "SD": (3, 3), "IA": (4, 3), "IN": (5, 3), "OH": (6, 3),
    "PA": (7, 3), "NJ": (8, 3), "CT": (9, 3), "RI": (10, 3),
    "CA": (0, 4), "UT": (1, 4), "CO": (2, 4), "NE": (3, 4), "MO": (4, 4), "KY": (5, 4), "WV": (6, 4),
    "VA": (7, 4), "MD": (8, 4), "DE": (9, 4),
    "AZ": (1, 5), "NM": (2, 5), "KS": (3, 5), "AR": (4, 5), "TN": (5, 5), "NC": (6, 5), "SC": (7, 5), "DC": (8, 5),
    "OK": (3, 6), "LA": (4, 6), "MS": (5, 6), "AL": (6, 6), "GA": (7, 6),
    "HI": (0, 7), "TX": (3, 7), "FL": (8, 7),
}
assert len(STATE_GRID) == 51


def view_columns():
    with psycopg.connect(CONNINFO) as conn:
        rows = conn.execute("""SELECT table_name, column_name, data_type FROM information_schema.columns
                               WHERE table_schema = 'analytics' AND table_name = ANY(%s)
                               ORDER BY table_name, ordinal_position""", (VIEWS,)).fetchall()
    cols = {v: [] for v in VIEWS}
    for table, column, dtype in rows:
        cols[table].append((column, TYPE_MAP[dtype]))
    return cols


# Calculated columns: (table, name, DAX). The prescriber-mix visuals tell one story (NPs/PAs vs primary care
# physicians), so every other specialty is rolled into a single group: three clearly different colours.
CALC_COLUMNS = [
    ("specialty_year", "Prescriber Group",
     "SWITCH ( specialty_year[specialty_group],\n"
     '    "Nurse Practitioner / PA", "NPs / PAs",\n'
     '    "Primary Care", "Primary care physicians",\n'
     '    "All other prescribers" )'),
]

def table_tmdl(view, columns):
    out = [f"table {view}", f"\tlineageTag: {tag(view)}", ""]
    for home, name, dax in CALC_COLUMNS:
        if home == view:
            out += [f"\tcolumn {q(name)} =", indent(dax, 3), "\t\tdataType: string",
                    f"\t\tlineageTag: {tag(view, 'calc', name)}", "\t\tsummarizeBy: none", "",
                    "\t\tannotation SummarizationSetBy = Automatic", ""]
    for home, name, dax, fmt, folder in MEASURES:
        if home != view:
            continue
        if "\n" in dax:
            out += [f"\tmeasure {q(name)} =", indent(dax, 3)]
        else:
            out.append(f"\tmeasure {q(name)} = {dax}")
        if fmt:
            out.append(f"\t\tformatString: {fmt}")
        out += [f"\t\tdisplayFolder: {folder}", f"\t\tlineageTag: {tag(view, 'm', name)}", ""]
    for col, dtype in columns:
        out += [f"\tcolumn {col}", f"\t\tdataType: {dtype}"]
        if dtype == "double":
            out.append("\t\tformatString: #,0.00")
        elif dtype == "int64":
            out.append("\t\tformatString: 0")
        if col in HIDDEN:
            out.append("\t\tisHidden")
        out += [f"\t\tlineageTag: {tag(view, col)}",
                f"\t\tsummarizeBy: {'none' if dtype == 'string' or col in HIDDEN else 'sum'}",
                f"\t\tsourceColumn: {col}", "", "\t\tannotation SummarizationSetBy = Automatic", ""]
    m = ("let\n    Source = PostgreSQL.Database(PgServer, PgDatabase),\n"
         f'    Data = Source{{[Schema = "analytics", Item = "{view}"]}}[Data]\nin\n    Data')
    out += [f"\tpartition {view} = m", "\t\tmode: import", "\t\tsource =", indent(m, 4), "",
            "\tannotation PBI_ResultType = Table", ""]
    return "\n".join(out)


def build_model():
    shutil.rmtree(SM, ignore_errors=True)
    d = SM / "definition"
    cols = view_columns()
    write_json(SM / "definition.pbism", {"$schema": S_PBISM, "version": "4.0", "settings": {}})
    write(d / "database.tmdl", "database\n\tcompatibilityLevel: 1600\n")
    tables = VIEWS + ["DimYear", "StateGrid"]
    write(d / "model.tmdl", "\n".join([
        "model Model", "\tculture: en-US", "\tdefaultPowerBIDataSourceVersion: powerBI_V3",
        "\tsourceQueryCulture: en-US", "\tdataAccessOptions", "\t\tlegacyRedirects", "\t\treturnErrorValuesAsNull",
        "", "annotation __PBI_TimeIntelligenceEnabled = 0", "",
        *[f"ref table {t}" for t in tables], ""]))
    write(d / "expressions.tmdl", "\n".join([
        'expression PgServer = "localhost" meta [IsParameterQuery = true, Type = "Text", IsParameterQueryRequired = true]',
        f"\tlineageTag: {tag('PgServer')}", "", "\tannotation PBI_ResultType = Text", "",
        'expression PgDatabase = "opioid_analytics" meta [IsParameterQuery = true, Type = "Text", IsParameterQueryRequired = true]',
        f"\tlineageTag: {tag('PgDatabase')}", "", "\tannotation PBI_ResultType = Text", ""]))
    for v in VIEWS:
        write(d / "tables" / f"{v}.tmdl", table_tmdl(v, cols[v]))
    write(d / "tables" / "DimYear.tmdl", "\n".join([
        "table DimYear", f"\tlineageTag: {tag('DimYear')}", "",
        "\tcolumn Year", "\t\tdataType: int64", "\t\tisKey", "\t\tformatString: 0",
        f"\t\tlineageTag: {tag('DimYear', 'Year')}", "\t\tsummarizeBy: none", "\t\tisNameInferred",
        "\t\tsourceColumn: [Year]", "", "\t\tannotation SummarizationSetBy = Automatic", "",
        "\tpartition DimYear = calculated", "\t\tmode: import",
        '\t\tsource = SELECTCOLUMNS ( GENERATESERIES ( 2013, 2024, 1 ), "Year", [Value] )', ""]))
    rows = ", ".join(f'{{ "{a}", {x}, {y} }}' for a, (x, y) in STATE_GRID.items())
    grid_cols = []
    for col, dtype in [("state_abbr", "string"), ("tile_x", "int64"), ("tile_y", "int64")]:
        grid_cols += [f"\tcolumn {col}", f"\t\tdataType: {dtype}", *(["\t\tisKey"] if col == "state_abbr" else []),
                      f"\t\tlineageTag: {tag('StateGrid', col)}", "\t\tsummarizeBy: none", "\t\tisNameInferred",
                      f"\t\tsourceColumn: [{col}]", "", "\t\tannotation SummarizationSetBy = Automatic", ""]
    write(d / "tables" / "StateGrid.tmdl", "\n".join([
        "table StateGrid", f"\tlineageTag: {tag('StateGrid')}", "", *grid_cols,
        "\tpartition StateGrid = calculated", "\t\tmode: import", "\t\tsource =",
        indent(f'DATATABLE ( "state_abbr", STRING, "tile_x", INTEGER, "tile_y", INTEGER, {{ {rows} }} )', 4), ""]))
    rels = [f"relationship {tag('rel', v)}\n\tfromColumn: {v}.year\n\ttoColumn: DimYear.Year\n" for v in VIEWS]
    rels.append(f"relationship {tag('rel', 'stategrid')}\n\tfromColumn: state_year.state_abbr\n"
                "\ttoColumn: StateGrid.state_abbr\n")
    write(d / "relationships.tmdl", "\n".join(rels))


# =====================================================================
# Report
#
# Design (adapted from public-health / healthcare dashboard practice):
#   * dark-teal navigation rail on the left: brand, vertical page buttons, data credit
#   * page title + one-line takeaway top-left, filters top-right
#   * KPI cards with an accent strip, big number, label and a context line (comparison / trend)
#   * white rounded tiles on a mint-grey canvas; 6-8 visuals per page
#   * one colour meaning everywhere: teal = prescribing, coral = deaths
#   * per-state detail in a hover tooltip page; methodology on a Data Notes page
# =====================================================================
RAIL, TEAL, CORAL, MUTED = "#0B3D3A", "#0F766E", "#E4572E", "#7C8F8D"
INDIGO, AMBER = "#4C5FD5", "#B7791F"      # NPs/PAs (the highlighted group), outliers (flag for review)
PAGE_BG, TILE_BORDER, INK, INK_2, MINT = "#EEF4F3", "#D5E3E0", "#10302E", "#5B6B6A", "#A7D7CF"
X0, W = 184, 1080          # content area to the right of the rail


def lit(v):
    return {"expr": {"Literal": {"Value": v}}}


def s(text):
    return lit("'" + text.replace("'", "''") + "'")


def solid(hex_):
    return {"solid": {"color": s(hex_)}}


def field(entity, prop, measure=False):
    return {("Measure" if measure else "Column"): {"Expression": {"SourceRef": {"Entity": entity}}, "Property": prop}}


def C(entity, prop):
    return (entity, prop, False)


def M(prop):
    home = next(h for h, n, *_ in MEASURES if n == prop)
    return (home, prop, True)


LABELS = {"specialty_group": "Prescriber group", "state_name": "State", "state_abbr": "State",
          "census_region": "Region", "Year": "Year"}


def MN(prop, name):
    """Measure with a display name for this visual only."""
    return (*M(prop), name)


def projections(fields):
    out = []
    for e, p, m, *name in fields:
        pr = {"field": field(e, p, m), "queryRef": f"{e}.{p}", "nativeQueryRef": p}
        if name:
            pr["displayName"] = name[0]
        elif p in LABELS:
            pr["displayName"] = LABELS[p]
        out.append(pr)
    return {"projections": out}


def tile(title=None, subtitle=None, background="#FFFFFF", border=True, tooltip_page=None, radius=12,
         pad=(12, 10, 14, 14)):
    """Container formatting shared by every visual: white rounded tile, bold title, grey subtitle."""
    objs = {
        "background": [{"properties": {"show": lit("true"), "color": solid(background), "transparency": lit("0D")}}],
        "border": [{"properties": {"show": lit("true" if border else "false"), "color": solid(TILE_BORDER),
                                   "radius": lit(f"{radius}D")}}],
        "dropShadow": [{"properties": {"show": lit("false")}}],
        "padding": [{"properties": {"top": lit(f"{pad[0]}D"), "bottom": lit(f"{pad[1]}D"),
                                    "left": lit(f"{pad[2]}D"), "right": lit(f"{pad[3]}D")}}],
        "title": [{"properties": {"show": lit("true" if title else "false"), **({
            "text": s(title), "fontColor": solid(INK), "fontSize": lit("14D"), "bold": lit("true"),
            "fontFamily": s("Segoe UI Semibold")} if title else {})}}],
    }
    if subtitle:
        objs["subTitle"] = [{"properties": {"show": lit("true"), "text": s(subtitle), "fontColor": solid(INK_2),
                                            "fontSize": lit("11D"), "titleWrap": lit("true")}}]
    if tooltip_page:
        # exactly the form Power BI Desktop writes for a report-page tooltip
        objs["visualTooltip"] = [{"properties": {"type": s("ReportPage"), "section": s(tooltip_page)}}]
    return objs


AXIS_TITLES_OFF = {"categoryAxis": [{"properties": {"showAxisTitle": lit("false"), "labelColor": solid(INK_2)}}],
                   "valueAxis": [{"properties": {"showAxisTitle": lit("false"), "labelColor": solid(INK_2)}}]}
# data labels: 11pt bold everywhere so values read at a glance
LABELS_ON = {"labels": [{"properties": {"show": lit("true"), "color": solid(INK), "fontSize": lit("11D"),
                                        "bold": lit("true")}}]}
YEAR = C("DimYear", "Year")


def series_colour(measure, hex_):
    home = next(h for h, n, *_ in MEASURES if n == measure)
    return {"properties": {"fill": solid(hex_)}, "selector": {"metadata": f"{home}.{measure}"}}


def chart(vtype, roles, title, subtitle=None, sort=None, objects=None, colours=None, tooltip_page=None):
    if vtype in ("lineChart", "clusteredBarChart", "clusteredColumnChart", "scatterChart"):
        objects = {**AXIS_TITLES_OFF, **(objects or {})}
    if colours:
        objects = {**(objects or {}), "dataPoint": [series_colour(m, c) for m, c in colours.items()]}
    # axis titles off everywhere (also when a chart customises an axis), readable 11pt axis labels and
    # legends, every year shown on year axes
    for axis in ("categoryAxis", "valueAxis"):
        if objects and axis in objects:
            objects[axis][0]["properties"].setdefault("showAxisTitle", lit("false"))
            objects[axis][0]["properties"].setdefault("fontSize", lit("11D"))
    if objects and "legend" in objects:
        objects["legend"][0]["properties"].setdefault("fontSize", lit("11D"))
    if objects and any(YEAR in fl for fl in roles.values()):
        objects.setdefault("categoryAxis", [{"properties": {"showAxisTitle": lit("false")}}])
        objects["categoryAxis"][0]["properties"]["axisType"] = s("Categorical")
    v = {"visualType": vtype, "query": {"queryState": {r: projections(f) for r, f in roles.items()}},
         "visualContainerObjects": tile(title, subtitle, tooltip_page=tooltip_page), "drillFilterOtherVisuals": True}
    if sort:
        (e, p, m), direction = sort
        v["query"]["sortDefinition"] = {"sort": [{"field": field(e, p, m), "direction": direction}],
                                        "isDefaultSort": False}
    if objects:
        v["objects"] = objects
    return v


def textbox(paragraphs, background=None, radius=12, pad=(12, 10, 14, 14), border=False, align=None):
    """paragraphs: list of (text, size, bold, colour), or a list of such tuples for several runs on one line."""
    def run(t, size, bold, col):
        return {"value": t, "textStyle": {"fontSize": f"{size}pt", "color": col,
                                          **({"fontWeight": "bold"} if bold else {})}}
    # empty paragraph list = pure colour block (strips, rails): no text, so no overflow scrollbar
    paras = [{"textRuns": [run(*r) for r in (p if isinstance(p, list) else [p])],
              **({"horizontalTextAlignment": align} if align else {})} for p in paragraphs if p]
    v = {"visualType": "textbox", "drillFilterOtherVisuals": True,
         "objects": {"general": [{"properties": {"paragraphs": paras}}]}}
    v["visualContainerObjects"] = tile(background=background, border=border, radius=radius, pad=pad) if background else \
        {"background": [{"properties": {"show": lit("false")}}]}
    return v


def card(measure, label, value_colour=INK, size=28, show_label=True, background="#FFFFFF", pad=(6, 4, 14, 14)):
    v = {"visualType": "card", "query": {"queryState": {"Values": projections([M(measure)])}},
         "objects": {
             "labels": [{"properties": {"color": solid(value_colour), "fontSize": lit(f"{size}D"),
                                        "fontFamily": s("Segoe UI Semibold")}}],
             "categoryLabels": [{"properties": {"show": lit("true" if show_label else "false"),
                                                "color": solid(INK_2), "fontSize": lit("12D")}}]},
         "visualContainerObjects": tile(background=background, border=False, pad=pad),
         "drillFilterOtherVisuals": True}
    v["query"]["queryState"]["Values"]["projections"][0]["displayName"] = label
    return v


def slicer(entity, prop, title):
    return {"visualType": "slicer", "query": {"queryState": {"Values": projections([C(entity, prop)])}},
            "objects": {"data": [{"properties": {"mode": s("Dropdown")}}],
                        "header": [{"properties": {"text": s(title), "fontColor": solid(INK), "bold": lit("true")}}]},
            "visualContainerObjects": tile(pad=(6, 6, 12, 12)), "drillFilterOtherVisuals": True}


def navigator():
    state = lambda sid, props: {"properties": props, "selector": {"id": sid}}
    return {"visualType": "pageNavigator", "drillFilterOtherVisuals": True,
            "objects": {
                "layout": [{"properties": {"orientation": lit("1D"), "cellPadding": lit("6L")}}],
                "pages": [{"properties": {"showHiddenPages": lit("false"), "showTooltipPages": lit("false")}}],
                "shape": [{"properties": {"tileShape": s("rectangleRounded"), "rectangleRoundedCurve": lit("8L")}}],
                "fill": [state("default", {"show": lit("true"), "fillColor": solid(RAIL), "transparency": lit("0D")}),
                         state("hover", {"fillColor": solid("#14524E")}),
                         state("selected", {"fillColor": solid("#16605B")})],
                "text": [state("default", {"fontColor": solid("#CFE3E0"), "fontSize": lit("12D"),
                                           "horizontalAlignment": s("left"), "leftMargin": lit("14L")}),
                         state("selected", {"fontColor": solid("#FFFFFF"), "bold": lit("true")})],
                "outline": [state("default", {"show": lit("false")})],
                "accentBar": [state("default", {"show": lit("false")}),
                              state("selected", {"show": lit("true"), "position": s("Left"),
                                                 "color": solid(MINT), "width": lit("4D")})],
            },
            "visualContainerObjects": {"background": [{"properties": {"show": lit("false")}}]}}


class Page:
    def __init__(self, name, display, width=1280, height=720, kind=None):
        self.name, self.display, self.visuals = name, display, []
        self.no_filter = []          # (source, target) visual pairs that must not filter each other
        self.width, self.height, self.kind = width, height, kind

    def add(self, vid, x, y, w, h, visual):
        n = len(self.visuals)
        self.visuals.append({"$schema": S_VISUAL, "name": vid, "visual": visual,
                             "position": {"x": x, "y": y, "z": n * 1000, "height": h, "width": w, "tabOrder": n * 1000}})

    def json(self):
        page = {"$schema": S_PAGE, "name": self.name, "displayName": self.display, "displayOption": "FitToPage",
                "height": self.height, "width": self.width,
                "objects": {"background": [{"properties": {"color": solid(PAGE_BG), "transparency": lit("0D"),
                                                           "image": {"image": {
                                                               "name": s("page_background.png"),
                                                               "url": {"expr": {"ResourcePackageItem": {
                                                                   "PackageName": "RegisteredResources", "PackageType": 1,
                                                                   "ItemName": "page_background.png"}}},
                                                               "scaling": s("Fit")}}}}],
                            "outspace": [{"properties": {"color": solid(PAGE_BG)}}]}}
        if self.no_filter:
            page["visualInteractions"] = [{"source": a, "target": b, "type": "NoFilter"} for a, b in self.no_filter]
        if self.kind == "Tooltip":
            # same shape Power BI Desktop writes for a tooltip page
            page.update({"displayOption": "ActualSize", "visibility": "HiddenInViewMode", "type": "Tooltip",
                         "pageBinding": {"name": f"{self.name}Binding", "type": "Tooltip", "parameters": []}})
            page["objects"] = {"background": [{"properties": {"color": solid("#FFFFFF"), "transparency": lit("0D")}}]}
        return page


DASHBOARD_TITLE = "Medicare Opioid Prescribing vs. Overdose Deaths"
TOP = 88                     # content starts under the title banner


def rail_slicer():
    """Year filter styled for the dark rail."""
    v = slicer("DimYear", "Year", "Filter by year")
    v["objects"]["header"] = [{"properties": {"text": s("FILTER BY YEAR"), "fontColor": solid(MINT),
                                              "fontSize": lit("8D"), "bold": lit("true")}}]
    v["objects"]["items"] = [{"properties": {"fontColor": solid(INK), "background": solid("#FFFFFF")}}]
    v["visualContainerObjects"] = {"background": [{"properties": {"show": lit("false")}}],
                                   "padding": [{"properties": {"top": lit("0D"), "bottom": lit("0D"),
                                                               "left": lit("4D"), "right": lit("4D")}}]}
    return v


def frame(page, section, takeaway, year_filter=False):
    """Left rail (brand, navigation, filter, credit) + centred title banner: identical on every page."""
    page.add("rail", 0, 0, 168, 720, textbox([None], background=RAIL, radius=0, pad=(0, 0, 0, 0)))
    page.add("brand", 4, 14, 160, 88, textbox(
        [("Opioid Prescribing", 11, True, "#FFFFFF"), ("& Overdose Analysis", 11, True, "#FFFFFF"),
         ("Medicare Part D  ·  2013-2024", 8, False, MINT)], pad=(4, 0, 12, 4)))
    page.add("brandRule", 16, 104, 136, 2, textbox([None], background="#1E5B56", radius=0, pad=(0, 0, 0, 0)))
    page.add("navigator", 8, 116, 152, 196, navigator())
    if year_filter:
        page.add("railRule", 16, 330, 136, 2, textbox([None], background="#1E5B56", radius=0, pad=(0, 0, 0, 0)))
        page.add("slicerYear", 12, 342, 144, 60, rail_slicer())
    page.add("credit", 4, 584, 160, 128, textbox(
        [("DATA", 8, True, MINT), ("CMS Medicare Part D", 9, False, "#CFE3E0"), ("CDC  ·  US Census", 9, False, "#CFE3E0"),
         ("", 4, False, INK), ("Built by Isaac Agyapong", 8, True, MINT), ("PostgreSQL  ·  Power BI", 8, False, "#CFE3E0")],
        pad=(0, 0, 12, 4)))
    # centred title banner: dashboard name, then the section and its one-line takeaway
    # header band joined to the rail: together they frame every page like an application
    page.add("titleBanner", 168, 0, 1112, 74, textbox(
        [(DASHBOARD_TITLE, 20, True, "#FFFFFF"),
         [(section.upper() + "   ·   ", 12, True, MINT), (takeaway, 12, False, "#CFE3E0")]],
        background=RAIL, radius=0, align="center", pad=(10, 4, 16, 16)))
    page.add("titleAccent", 168, 74, 1112, 3, textbox([None], background=MINT, radius=0, pad=(0, 0, 0, 0)))


def kpi(page, i, x, y, w, measure, label, context, colour, h=128, size=28):
    page.add(f"kpiTile{i}", x, y, w, h, textbox([None], background="#FFFFFF", border=True))
    page.add(f"kpiAccent{i}", x + 14, y + 1, w - 28, 4, textbox([None], background=colour, radius=0,
                                                                 pad=(0, 0, 0, 0)))
    page.add(f"kpi{i}", x + 4, y + 8, w - 8, h - 38 if context else h - 12,
             card(measure, label, value_colour=colour, size=size))
    if context:
        page.add(f"kpiContext{i}", x + 4, y + h - 32, w - 8, 28,
                 card(context, "", value_colour=INK_2, size=11, show_label=False, pad=(0, 0, 14, 14)))


LINE_MARKERS = {"lineStyles": [{"properties": {"showMarker": lit("true"), "markerSize": lit("5D")}}]}


def build_pages():
    # ---------------------------------------------------------------- 1. Overview
    p1 = Page("nationalTrend", "Overview")
    frame(p1, "National overview", "Prescribing fell every year since 2013, while overdose deaths doubled, driven by fentanyl")
    kpis = [("Latest Opioid Rate", "Opioid share of prescriptions", "KPI Rate Context", TEAL),
            ("Rate Change Since 2013", "Change in prescribing rate", "KPI Change Context", TEAL),
            ("Peak Opioid Deaths", "Peak US opioid deaths", "KPI Peak Context", CORAL),
            ("Latest Opioid Deaths", "US opioid deaths, latest year", "KPI Deaths Context", CORAL)]
    for i, (m, label, ctx, colour) in enumerate(kpis):
        kpi(p1, i + 1, X0 + i * 274, TOP, 258, m, label, ctx, colour)
    no_value_axis = {"valueAxis": [{"properties": {"show": lit("false"), "gridlineShow": lit("false")}}]}
    # area chart: the shape of an 11-year decline
    p1.add("rateArea", X0, TOP + 140, 360, 480, chart(
        "areaChart", {"Category": [YEAR], "Y": [M("Opioid Rate")]},
        "Prescribing is down 40% in 11 years",
        "Opioids as a share of all Medicare Part D prescriptions", sort=(YEAR, "Ascending"),
        objects={**LABELS_ON, **no_value_axis, **LINE_MARKERS},
        colours={"Opioid Rate": TEAL}))
    # stacked columns: yearly total and what it is made of
    p1.add("deathColumns", X0 + 372, TOP + 140, 476, 480, chart(
        "columnChart", {"Category": [YEAR], "Y": [MN("Fentanyl-Involved Deaths", "Involving fentanyl-type drugs"),
                                                  MN("Other Opioid Deaths", "Other opioids only")]},
        "...but opioid deaths rose",
        "US opioid overdose deaths by year (CDC)", sort=(YEAR, "Ascending"),
        # inside a stacked column there is less room: 10pt white labels fit every segment
        objects={"labels": [{"properties": {"show": lit("true"), "color": solid("#FFFFFF"), "fontSize": lit("10D"),
                                            "bold": lit("true")}}], **no_value_axis},
        colours={"Fentanyl-Involved Deaths": CORAL, "Other Opioid Deaths": MUTED}))
    # donut: part-to-whole with only two parts
    p1.add("fentanylDonut", X0 + 860, TOP + 140, 220, 480, chart(
        "donutChart", {"Y": [MN("Latest Fentanyl-Involved Deaths", "Fentanyl-type"),
                             MN("Latest Other Opioid Deaths", "Other opioids")]},
        "Fentanyl drives the crisis", "Share of opioid deaths, latest year",
        objects={"labels": [{"properties": {"show": lit("true"), "labelStyle": s("Percent of total"), "labelPrecision": lit("0L"), "percentageLabelPrecision": lit("0L"),
                                            "color": solid(INK), "fontSize": lit("12D")}}],
                 "legend": [{"properties": {"show": lit("true"), "position": s("Bottom"), "fontSize": lit("10D")}}]},
        colours={"Latest Fentanyl-Involved Deaths": CORAL, "Latest Other Opioid Deaths": MUTED}))

    # ---------------------------------------------------------------- 2. States
    p2 = Page("states", "States")
    frame(p2, "State comparison", "The states that prescribe the most are not the states with the most overdose deaths",
          year_filter=True)
    by_measure = lambda m: {"solid": {"color": {"expr": field("state_year", m, True)}}}
    # conditional formatting in a matrix must name the measure it applies to (metadata = its queryRef)
    every_cell = {"data": [{"dataViewWildcard": {"matchingOption": 1}}], "metadata": "state_year.Tile Label"}
    hidden_header = {"fontColor": solid("#FFFFFF"), "backColor": solid("#FFFFFF"), "fontSize": lit("6D")}
    tile_map = chart(
        "pivotTable", {"Rows": [C("StateGrid", "tile_y")], "Columns": [C("StateGrid", "tile_x")],
                       "Values": [M("Tile Label")]},
        "Overdose deaths per 100,000 by state", "Hover over a state for its profile  ·  click to filter the page",
        tooltip_page="stateTooltip",
        objects={
            "values": [{"properties": {"fontSize": lit("13D"), "bold": lit("true"),
                                       "backColorPrimary": solid("#FFFFFF"), "backColorSecondary": solid("#FFFFFF")}},
                       {"properties": {"backColor": by_measure("Death Rate Colour"),
                                       "fontColor": by_measure("Tile Label Colour")}, "selector": every_cell}],
            "columnHeaders": [{"properties": hidden_header}],
            "rowHeaders": [{"properties": hidden_header}],
            "subTotals": [{"properties": {"rowSubtotals": lit("false"), "columnSubtotals": lit("false")}}],
            "grid": [{"properties": {"gridVertical": lit("true"), "gridVerticalColor": solid("#FFFFFF"),
                                     "gridVerticalWeight": lit("4D"), "gridHorizontal": lit("true"),
                                     "gridHorizontalColor": solid("#FFFFFF"), "gridHorizontalWeight": lit("4D"),
                                     "outlineColor": solid("#FFFFFF"), "rowPadding": lit("10D")}}],
        })
    tile_map["query"]["queryState"]["Values"]["projections"][0]["displayName"] = " "
    p2.add("tileMap", X0, TOP, 540, 620, tile_map)
    p2.add("mapLegend", X0 + 16, TOP + 574, 508, 36, textbox([[
        ("Deaths per 100k   ", 9, True, INK_2),
        ("■ ", 14, False, "#FBE3D6"), ("under 20   ", 9, False, INK_2),
        ("■ ", 14, False, "#F5B48F"), ("20-30   ", 9, False, INK_2),
        ("■ ", 14, False, "#EE8452"), ("30-40   ", 9, False, INK_2),
        ("■ ", 14, False, "#D95926"), ("40-50   ", 9, False, INK_2),
        ("■ ", 14, False, "#9E3A12"), ("50+", 9, False, INK_2)]], pad=(4, 0, 0, 0)))
    no_axis = {"valueAxis": [{"properties": {"show": lit("false"), "gridlineShow": lit("false")}}]}
    p2.add("topPrescribing", X0 + 556, TOP, 524, 304, chart(
        "clusteredBarChart", {"Category": [C("state_year", "state_name")], "Y": [M("Top 10 Prescribing Rate")]},
        "Top 10 states: opioid prescribing rate (share of Part D prescriptions)", None,
        tooltip_page="stateTooltip", sort=(M("Top 10 Prescribing Rate"), "Descending"),
        objects={**LABELS_ON, **no_axis, "dataPoint": [{"properties": {"fill": solid(TEAL)}}]}))
    # table with data bars: the deadliest states, and where each one ranks for prescribing
    data_bar = lambda measure, colour: {
        "properties": {"dataBars": {"positiveColor": solid(colour), "negativeColor": solid(colour),
                                    "axisColor": solid("#FFFFFF"), "reverseDirection": lit("false"),
                                    "hideText": lit("false")}},
        "selector": {"metadata": f"state_year.{measure}"}}
    # rankings always rank all 51 states: clicking a state on the map must not filter them
    p2.no_filter += [("tileMap", "topPrescribing"), ("tileMap", "deathStates"),
                     ("topPrescribing", "deathStates"), ("deathStates", "topPrescribing")]
    p2.add("deathStates", X0 + 556, TOP + 316, 524, 304, chart(
        "tableEx", {"Values": [C("state_year", "state_name"),
                               MN("Top 10 Death Rate", "Deaths /100k"),
                               MN("Death State Prescribing Rate", "Rx rate"),
                               MN("Death State Prescribing Rank", "Rx rank")]},
        "The 10 deadliest states are not the top prescribers",
        "Rx rate = opioid share of prescriptions; Rx rank = prescribing rank of 51",
        tooltip_page="stateTooltip", sort=(M("Top 10 Death Rate"), "Descending"),
        objects={"columnFormatting": [data_bar("Top 10 Death Rate", "#F5B48F"),
                                      data_bar("Death State Prescribing Rate", MINT)],
                 "values": [{"properties": {"fontSize": lit("10D")}}],
                 "columnHeaders": [{"properties": {"fontSize": lit("10D"), "bold": lit("true")}}],
                 "total": [{"properties": {"totals": lit("false")}}]}))

    # ---------------------------------------------------------------- 3. Prescribers
    p3 = Page("prescribers", "Prescribers")
    frame(p3, "Who prescribes", "Nurse practitioners and PAs now write almost a third of Medicare opioid prescriptions",
          year_filter=True)
    # treemap: part-to-whole across 13 groups; the big blocks carry the story
    # colour with purpose: NPs/PAs in coral (matches their line on the right), physician groups in
    # teal shades, the roll-up in neutral grey
    group_colours = {"NPs / PAs": INDIGO, "Primary care physicians": TEAL, "All other prescribers": "#C5CFCE"}
    group_col = field("specialty_year", "Prescriber Group")
    tile_colours = [{"properties": {"fill": solid(c)},
                     "selector": {"data": [{"scopeId": {"Comparison": {
                         "ComparisonKind": 0, "Left": group_col, "Right": {"Literal": {"Value": f"'{g}'"}}}}}]}}
                    for g, c in group_colours.items()]
    # two donuts, 2019 and 2024: the indigo NP/PA slice visibly grows, the teal primary care slice shrinks
    p3.add("donutPanel", X0, TOP, 540, 620, textbox(
        [("NPs and PAs grew from 23% to 30% of opioid prescriptions", 14, True, INK),
         ("Share of Medicare opioid prescriptions by prescriber group", 11, False, INK_2)],
        background="#FFFFFF", border=True, pad=(12, 10, 14, 14)))
    for k, (year, measure) in enumerate([(2019, "Share 2019"), (2024, "Share 2024")]):
        x = X0 + 10 + k * 262
        p3.add(f"donutYear{year}", x, TOP + 100, 258, 48, textbox([(str(year), 20, True, TEAL if year == 2024 else INK_2)],
                                                                align="center", pad=(0, 0, 0, 0)))
        d = chart(
            "donutChart", {"Category": [C("specialty_year", "Prescriber Group")],
                           "Y": [MN(measure, f"Share of opioid prescriptions, {year}")]}, None,
            objects={"labels": [{"properties": {"show": lit("true"), "labelStyle": s("Percent of total"),
                                                "labelPrecision": lit("0L"), "percentageLabelPrecision": lit("0L"),
                                                "fontSize": lit("14D"), "bold": lit("true"), "color": solid(INK)}}],
                     "legend": [{"properties": {"show": lit("false")}}],
                     "dataPoint": tile_colours})
        d["visualContainerObjects"] = tile(border=False, pad=(0, 0, 0, 0))
        p3.add(f"donut{year}", x, TOP + 150, 258, 390, d)
    swatch = lambda g: [("■ ", 16, False, group_colours[g]), (g + "      ", 12, False, INK)]
    p3.add("donutLegend", X0 + 10, TOP + 552, 520, 56, textbox(
        [[r for g in group_colours for r in swatch(g)]], align="center", pad=(0, 0, 0, 0)))
    outlier_kpis = [("High Outliers", "Outliers"),
                    ("Outlier Share of Prescribers", "of prescribers"),
                    ("Outlier Share of Claims", "of opioid claims")]
    for i, (m, label) in enumerate(outlier_kpis):
        kpi(p3, 10 + i, X0 + 556 + i * 180, TOP, 164, m, label, None, AMBER, h=112, size=24)
    # (outlier cards have no context line, so their label gets the full height)
    p3.add("outlierTable", X0 + 556, TOP + 124, 524, 496, chart(
        "tableEx", {"Values": [C("outlier_summary", "specialty_group"), MN("High Outliers", "Outliers"),
                               MN("Outlier Share of Claims", "Share of claims")]},
        "Peer outliers by prescriber group (latest selected year)", None,
        sort=(M("High Outliers"), "Descending"),
        objects={"values": [{"properties": {"fontSize": lit("11D")}}],
                 "columnHeaders": [{"properties": {"fontSize": lit("11D"), "bold": lit("true")}}],
                 "total": [{"properties": {"fontSize": lit("11D")}}],
                 "grid": [{"properties": {"rowPadding": lit("1D")}}],
                 "columnFormatting": [
            {"properties": {"dataBars": {"positiveColor": solid("#F2D49B"), "negativeColor": solid("#F2D49B"),
                                         "axisColor": solid("#FFFFFF"), "reverseDirection": lit("false"),
                                         "hideText": lit("false")}},
             "selector": {"metadata": "outlier_summary.High Outliers"}}]}))

    # ---------------------------------------------------------------- 4. Data notes
    p4 = Page("dataNotes", "Data Notes")
    frame(p4, "Data notes", "Sources, definitions and limitations")
    cols = [
        ("Sources", [
            "CMS Medicare Part D Prescribers by Provider, 2019-2024 (7.8M prescriber-years)",
            "CMS Medicare Part D Opioid Prescribing Rates by Geography, 2013-2024",
            "CDC VSRR Provisional Drug Overdose Death Counts, 2015-2024",
            "US Census Bureau state population estimates",
            "Loaded and modelled in PostgreSQL; this report imports the analytics views"]),
        ("Definitions", [
            "Opioid rate = opioid claims / all Part D claims",
            "Fentanyl-type (synthetic) opioids = ICD-10 T40.4",
            "Prescription-type opioids = natural & semi-synthetic opioids (T40.2)",
            "Death rates are per 100,000 residents",
            "Peer outlier = at or above the 99th percentile and 3x the median of the same specialty, "
            "with 100+ total and 50+ opioid claims"]),
        ("Limitations", [
            "Medicare Part D only: mostly adults 65+ and people with disabilities",
            "CMS suppresses prescriber opioid counts of 1-10; these are 2.2% of claims",
            "2024 CDC counts are provisional",
            "State comparisons describe states, not individual patients",
            "An outlier is a flag for review, not evidence of inappropriate prescribing"]),
    ]
    for i, (heading, lines) in enumerate(cols):
        x = X0 + i * 364
        p4.add(f"notes{i + 1}", x, TOP, 348, 620, textbox(
            [(heading, 18, True, INK)] + [("•  " + t, 12, False, INK) for t in lines],
            background="#FFFFFF", border=True, pad=(20, 12, 20, 20)))
        p4.add(f"notesAccent{i + 1}", x + 16, TOP + 1, 316, 4, textbox([None], background=TEAL, radius=0,
                                                                     pad=(0, 0, 0, 0)))

    # ---------------------------------------------------------------- tooltip: state profile
    tt = Page("stateTooltip", "State Tooltip", width=320, height=240, kind="Tooltip")
    tt.add("ttHeader", 0, 0, 320, 64, textbox([None], background=RAIL, radius=0, pad=(0, 0, 0, 0)))
    tt.add("ttName", 4, 2, 312, 38, card("Selected State", "", value_colour="#FFFFFF", size=16, show_label=False,
                                         background=RAIL))
    tt.add("ttRank", 4, 36, 312, 26, card("Prescribing Rank Text", "", value_colour=MINT, size=10, show_label=False,
                                          background=RAIL, pad=(0, 0, 14, 14)))
    tt.add("ttRate", 8, 72, 148, 76, card("State Opioid Rate", "Prescribing rate", value_colour=TEAL, size=18))
    tt.add("ttDeath", 164, 72, 148, 76, card("Overdose Death Rate", "Overdose deaths / 100k", value_colour=CORAL, size=18))
    tt.add("ttFent", 8, 156, 148, 76, card("Fentanyl Death Rate", "Fentanyl deaths / 100k", value_colour=CORAL, size=18))
    tt.add("ttRx", 164, 156, 148, 76, card("Rx Opioid Death Rate", "Rx-opioid deaths / 100k", value_colour=TEAL, size=18))
    return [p1, p2, p3, p4, tt]


def build_report():
    shutil.rmtree(RPT, ignore_errors=True)
    d = RPT / "definition"
    write_json(RPT / "definition.pbir", {"$schema": S_PBIR, "version": "4.0",
                                         "datasetReference": {"byPath": {"path": f"../{NAME}.SemanticModel"}}})
    write_json(d / "version.json", {"$schema": S_VERSION, "version": "2.0.0"})
    write_json(d / "report.json", {
        "$schema": S_REPORT,
        "themeCollection": {
            "baseTheme": {"name": BASE_THEME, "reportVersionAtImport": "5.59", "type": "SharedResources"},
            "customTheme": {"name": CUSTOM_THEME, "reportVersionAtImport": "5.59", "type": "RegisteredResources"}},
        "layoutOptimization": "None",
        "resourcePackages": [
            {"name": "SharedResources", "type": "SharedResources",
             "items": [{"name": BASE_THEME, "path": f"BaseThemes/{BASE_THEME}.json", "type": "BaseTheme"}]},
            {"name": "RegisteredResources", "type": "RegisteredResources",
             "items": [{"name": CUSTOM_THEME, "path": CUSTOM_THEME, "type": "CustomTheme"},
                       {"name": "page_background.png", "path": "page_background.png", "type": "Image"}]}]})
    static = RPT / "StaticResources"
    (static / "SharedResources" / "BaseThemes").mkdir(parents=True, exist_ok=True)
    shutil.copy(find_base_theme(), static / "SharedResources" / "BaseThemes" / f"{BASE_THEME}.json")
    write_json(static / "RegisteredResources" / CUSTOM_THEME, {
        "name": "Rx Insight",
        "dataColors": [TEAL, CORAL, MUTED, "#C9A227", "#5B8DB8", "#8E6C8A", "#3E7C59", "#B5523B"],
        "foreground": "#0B0B0B", "background": "#FFFFFF", "tableAccent": BLUE})
    # page background image (generated by Python/make_background.py)
    subprocess.run([sys.executable, str(ROOT / "Python" / "make_background.py")], check=True)
    shutil.copy(DASH / "assets" / "page_background.png", static / "RegisteredResources" / "page_background.png")
    pages = build_pages()
    write_json(d / "pages" / "pages.json", {"$schema": S_PAGES, "pageOrder": [p.name for p in pages],
                                            "activePageName": pages[0].name})
    for p in pages:
        write_json(d / "pages" / p.name / "page.json", p.json())
        for v in p.visuals:
            write_json(d / "pages" / p.name / "visuals" / v["name"] / "visual.json", v)


def main():
    build_model()
    build_report()
    write_json(DASH / f"{NAME}.pbip", {"$schema": S_PBIP, "version": "1.0",
                                       "artifacts": [{"report": {"path": f"{NAME}.Report"}}],
                                       "settings": {"enableAutoRecovery": True}})
    print(f"wrote dashboard/{NAME}.pbip")


if __name__ == "__main__":
    main()
