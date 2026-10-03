"""Emission factors (kg CO2e per unit of activity).

Electricity factors track the carbon intensity of each region's grid mix, which
is the single biggest source of variation between users. Diet factors use
Poore & Nemecek (2018) global medians and are intentionally shared across
regions, because the study does not break them down reliably per country.

Every entry set is stamped with the version below. Footprint rows store that
version so a later factor update never silently rewrites historical totals.
"""

FACTORS_VERSION = 2

# Meat/plant diet medians are region-independent for now. Only the grid differs.
_DIET = {
    "meat_meal": 5.0,
    "plant_meal": 2.0,
}

# Average passenger car, roughly 0.21 kg/km. Fuel mix varies a little by region
# but not enough to matter next to the grid difference.
_CAR_KM = 0.21

# g CO2e/kWh converted to kg, then dropped back by the kWh unit.
GRID_FACTORS_G_PER_KWH = {
    "world": 475,
    "us": 372,
    "eu": 275,
    "gb": 207,
    "fr": 56,
    "de": 349,
    "in": 713,
    "ca": 127,
    "au": 517,
    "br": 88,
}

REGION_LABELS = {
    "world": "World average",
    "us": "United States",
    "eu": "European Union",
    "gb": "United Kingdom",
    "fr": "France",
    "de": "Germany",
    "in": "India",
    "ca": "Canada",
    "au": "Australia",
    "br": "Brazil",
}

DEFAULT_REGION = "world"


def available_regions():
    return sorted(GRID_FACTORS_G_PER_KWH, key=lambda r: REGION_LABELS[r])


def region_codes():
    return available_regions()


def is_valid_region(region):
    # The isinstance guard matters: `[] in dict` raises TypeError on unhashable
    # input, which would turn a junk region into a 500 instead of a 400.
    return isinstance(region, str) and region in GRID_FACTORS_G_PER_KWH


def factors_for(region):
    """Return the factor set for a region, falling back to the world average."""
    region = region if is_valid_region(region) else DEFAULT_REGION
    return {
        "region": region,
        "factors_version": FACTORS_VERSION,
        "car_km": _CAR_KM,
        # g -> kg
        "electricity_kwh": GRID_FACTORS_G_PER_KWH[region] / 1000.0,
        "meat_meal": _DIET["meat_meal"],
        "plant_meal": _DIET["plant_meal"],
    }


def catalogue():
    """Everything the frontend needs to render labels and hints."""
    return {
        "default_region": DEFAULT_REGION,
        "factors_version": FACTORS_VERSION,
        "regions": [
            {
                "code": code,
                "label": REGION_LABELS[code],
                "electricity_kwh": GRID_FACTORS_G_PER_KWH[code] / 1000.0,
            }
            for code in available_regions()
        ],
        "units": {
            "car_km": "per km",
            "electricity_kwh": "per kWh",
            "meat_meal": "per meat meal",
            "plant_meal": "per plant meal",
        },
    }
