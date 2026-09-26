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
     "    CALCULATE ( [Specialty Opioid Claims], REMOVEFILTERS ( specialty_year[specialty_group] ) ) )", PCT1, "Prescribers"),
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
]


def view_columns():
    with psycopg.connect(CONNINFO) as conn:
        rows = conn.execute("""SELECT table_name, column_name, data_type FROM information_schema.columns
                               WHERE table_schema = 'analytics' AND table_name = ANY(%s)
                               ORDER BY table_name, ordinal_position""", (VIEWS,)).fetchall()
    cols = {v: [] for v in VIEWS}
    for table, column, dtype in rows:
        cols[table].append((column, TYPE_MAP[dtype]))
    return cols


def table_tmdl(view, columns):
    out = [f"table {view}", f"\tlineageTag: {tag(view)}", ""]
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
    tables = VIEWS + ["DimYear"]
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
    write(d / "relationships.tmdl", "\n".join(
        f"relationship {tag('rel', v)}\n\tfromColumn: {v}.year\n\ttoColumn: DimYear.Year\n" for v in VIEWS))


# =====================================================================
# Report
# =====================================================================
def lit(v):
    return {"expr": {"Literal": {"Value": v}}}


def s(text):
    return lit("'" + text.replace("'", "''") + "'")


def field(entity, prop, measure=False):
    return {("Measure" if measure else "Column"): {"Expression": {"SourceRef": {"Entity": entity}}, "Property": prop}}


def C(entity, prop):
    return (entity, prop, False)


def M(prop):
    home = next(h for h, n, *_ in MEASURES if n == prop)
    return (home, prop, True)


LABELS = {"specialty_group": "Prescriber group", "state_name": "State", "state_abbr": "State",
          "census_region": "Region", "Year": "Year"}


def projections(fields):
    out = []
    for e, p, m in fields:
        pr = {"field": field(e, p, m), "queryRef": f"{e}.{p}", "nativeQueryRef": p}
        if p in LABELS:
            pr["displayName"] = LABELS[p]
        out.append(pr)
    return {"projections": out}


def container_title(text, show=True):
    props = {"show": lit("true" if show else "false")}
    if show:
        props["text"] = s(text)
    return {"title": [{"properties": props}]}


AXIS_TITLES_OFF = {"categoryAxis": [{"properties": {"showAxisTitle": lit("false")}}],
                   "valueAxis": [{"properties": {"showAxisTitle": lit("false")}}]}
LABELS_ON = {"labels": [{"properties": {"show": lit("true")}}]}
YEAR = C("DimYear", "Year")


def chart(vtype, roles, title, sort=None, objects=None):
    if vtype in ("lineChart", "clusteredBarChart", "clusteredColumnChart"):
        objects = {**AXIS_TITLES_OFF, **(objects or {})}
    v = {"visualType": vtype, "query": {"queryState": {r: projections(f) for r, f in roles.items()}},
         "visualContainerObjects": container_title(title), "drillFilterOtherVisuals": True}
    if sort:
        (e, p, m), direction = sort
        v["query"]["sortDefinition"] = {"sort": [{"field": field(e, p, m), "direction": direction}],
                                        "isDefaultSort": False}
    if objects:
        v["objects"] = objects
    return v


def textbox(text, size, bold=False, color="#0B0B0B"):
    style = {"fontSize": f"{size}pt", "color": color}
    if bold:
        style["fontWeight"] = "bold"
    return {"visualType": "textbox", "drillFilterOtherVisuals": True,
            "objects": {"general": [{"properties": {"paragraphs": [{"textRuns": [{"value": text, "textStyle": style}]}]}}]}}


def card(measure):
    return {"visualType": "card", "query": {"queryState": {"Values": projections([M(measure)])}},
            "objects": {"categoryLabels": [{"properties": {"show": lit("true")}}]},
            "visualContainerObjects": container_title("", show=False), "drillFilterOtherVisuals": True}


def slicer(entity, prop, title):
    return {"visualType": "slicer", "query": {"queryState": {"Values": projections([C(entity, prop)])}},
            "objects": {"data": [{"properties": {"mode": s("Dropdown")}}], "header": [{"properties": {"text": s(title)}}]},
            "visualContainerObjects": container_title(title, show=False), "drillFilterOtherVisuals": True}


class Page:
    def __init__(self, name, display):
        self.name, self.display, self.visuals = name, display, []

    def add(self, vid, x, y, w, h, visual):
        n = len(self.visuals)
        self.visuals.append({"$schema": S_VISUAL, "name": vid, "visual": visual,
                             "position": {"x": x, "y": y, "z": n * 1000, "height": h, "width": w, "tabOrder": n * 1000}})


def header(page, title, subtitle):
    page.add("title", 24, 4, 1000, 56, textbox(title, 20, bold=True))
    page.add("subtitle", 24, 50, 1232, 34, textbox(subtitle, 11, color="#52514E"))


def build_pages():
    p1 = Page("nationalTrend", "National Trend")
    header(p1, "Medicare Opioid Prescribing vs. Overdose Deaths",
           "Prescribing fell every year since 2013 while overdose deaths doubled, driven by fentanyl. "
           "Sources: CMS Medicare Part D, CDC, US Census")
    for i, m in enumerate(["Latest Opioid Rate", "Rate Change Since 2013", "Peak Opioid Deaths", "Latest Synthetic Share"]):
        p1.add(f"kpi{i + 1}", 24 + i * 308, 92, 296, 104, card(m))
    p1.add("rateTrend", 24, 212, 612, 496, chart(
        "lineChart", {"Category": [YEAR], "Y": [M("Opioid Rate")]},
        "Opioid share of all Medicare Part D prescriptions", sort=(YEAR, "Ascending"),
        objects={"valueAxis": [{"properties": {"start": lit("0D"), "showAxisTitle": lit("false")}}], **LABELS_ON,
                 # line colours are set per series: the selector names the measure
                 "dataPoint": [{"properties": {"fill": {"solid": {"color": s(BLUE)}}},
                                "selector": {"metadata": "national_trend.Opioid Rate"}}]}))
    p1.add("deathTrend", 648, 212, 608, 496, chart(
        "lineChart", {"Category": [YEAR], "Y": [M("Synthetic Opioid Deaths"), M("Rx Opioid Deaths"), M("Heroin Deaths")]},
        "US opioid overdose deaths by drug type (CDC)", sort=(YEAR, "Ascending")))

    p2 = Page("states", "States")
    header(p2, "States: Prescribing Rate vs. Overdose Deaths",
           "High-prescribing states do not have higher overdose death rates. Use the Year filter to see any single year")
    p2.add("slicerYear", 24, 88, 200, 64, slicer("DimYear", "Year", "Year"))
    p2.add("scatter", 24, 160, 612, 548, chart(
        "scatterChart", {"Category": [C("state_year", "state_abbr")], "X": [M("State Opioid Rate")],
                         "Y": [M("Overdose Death Rate")]},
        "Opioid prescribing rate (x) vs. overdose deaths per 100,000 (y)",
        objects={"categoryLabels": [{"properties": {"show": lit("true")}}]}))
    p2.add("stateTable", 648, 88, 608, 620, chart(
        "tableEx", {"Values": [C("state_year", "state_name"), C("state_year", "census_region"),
                               M("State Opioid Rate"), M("Overdose Death Rate"), M("Fentanyl Death Rate"),
                               M("Rx Opioid Death Rate")]},
        "All states", sort=(M("State Opioid Rate"), "Descending")))

    p3 = Page("prescribers", "Prescribers")
    header(p3, "Who Prescribes: Specialties, Outliers and Rural Areas",
           "Nurse practitioners and PAs now write almost a third of Medicare opioid prescriptions; "
           "about 1% of each specialty are extreme peer outliers")
    p3.add("slicerYear", 24, 88, 200, 64, slicer("DimYear", "Year", "Year"))
    p3.add("specialtyShare", 24, 160, 612, 304, chart(
        "clusteredBarChart", {"Category": [C("specialty_year", "specialty_group")], "Y": [M("Share of Opioid Claims")]},
        "Share of all opioid prescriptions by prescriber group", sort=(M("Share of Opioid Claims"), "Descending"),
        objects={**LABELS_ON, "dataPoint": [{"properties": {"fill": {"solid": {"color": s(BLUE)}}}}]}))
    p3.add("npShift", 648, 88, 608, 180, chart(
        "lineChart", {"Category": [YEAR], "Y": [M("NP / PA Share"), M("Primary Care Share")]},
        "NP / PA vs. primary care physicians: share of opioid prescriptions", sort=(YEAR, "Ascending")))
    p3.add("ruralTrend", 648, 276, 608, 188, chart(
        "lineChart", {"Category": [YEAR], "Y": [M("Rural Opioid Rate"), M("Urban Opioid Rate")]},
        "Rural vs. urban prescribers: opioid share of prescriptions", sort=(YEAR, "Ascending")))
    p3.add("outlierTable", 24, 472, 1232, 236, chart(
        "tableEx", {"Values": [C("outlier_summary", "specialty_group"), M("Eligible Prescribers"),
                               M("High Outliers"), M("Outlier Share of Claims")]},
        "Peer outliers in the latest selected year (at or above the 99th percentile and 3x the median of their own specialty)",
        sort=(M("High Outliers"), "Descending")))
    return [p1, p2, p3]


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
             "items": [{"name": CUSTOM_THEME, "path": CUSTOM_THEME, "type": "CustomTheme"}]}]})
    static = RPT / "StaticResources"
    (static / "SharedResources" / "BaseThemes").mkdir(parents=True, exist_ok=True)
    shutil.copy(find_base_theme(), static / "SharedResources" / "BaseThemes" / f"{BASE_THEME}.json")
    write_json(static / "RegisteredResources" / CUSTOM_THEME, {
        "name": "Opioid Portfolio",
        "dataColors": [ORANGE, BLUE, AQUA, "#EDA100", "#E87BA4", "#008300", "#4A3AA7", "#E34948"],
        "foreground": "#0B0B0B", "background": "#FFFFFF", "tableAccent": BLUE})
    pages = build_pages()
    write_json(d / "pages" / "pages.json", {"$schema": S_PAGES, "pageOrder": [p.name for p in pages],
                                            "activePageName": pages[0].name})
    for p in pages:
        write_json(d / "pages" / p.name / "page.json", {"$schema": S_PAGE, "name": p.name, "displayName": p.display,
                                                         "displayOption": "FitToPage", "height": 720, "width": 1280})
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
