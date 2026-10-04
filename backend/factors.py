"""Emission factors (kg CO2e per unit of activity), with provenance for each value.

Electricity factors track the carbon intensity of each region's grid mix, which
is the single biggest source of variation between users. Car factors track the
average emissions of the vehicle fleet actually being driven, which is not the
same thing as the emissions of new cars being sold.

Diet factors use Poore & Nemecek (2018) global medians and are intentionally
shared across regions. That dataset is global by nature; there is no reliable
per-country equivalent, so pretending otherwise would mean inventing numbers.

Every value carries where it came from. `catalogue()` exposes that, and
`car_factor_is_default()` reports when a region has no measured figure of its own
and is standing in for the global default. Two figures being different is only
meaningful if you know they were measured the same way, so the basis is recorded
next to the number rather than in a comment nobody will read in two years.

## Why not EEA new-car data

The EEA publishes CO2 per km for new passenger cars by member state, which is
tempting because it is per-country and primary-source. It is the wrong basis
here: it is a type-approval figure for cars being sold *this year* (107 g/km EU
average), not the fleet being driven. Using it would understate a user's driving
emissions by roughly a third, while looking more rigorous than the global
average. Car factors below are fleet averages for that reason.
"""

from dataclasses import dataclass

FACTORS_VERSION = 3


@dataclass(frozen=True)
class Provenance:
    """Where a number came from, and what it actually measures."""

    source: str
    basis: str
    year: int | None = None

    def to_dict(self):
        return {"source": self.source, "basis": self.basis, "year": self.year}


# --- Diet -----------------------------------------------------------------
# Poore & Nemecek 2018 global medians. Region-independent by nature.
_DIET = {
    "meat_meal": 5.0,
    "plant_meal": 2.0,
}
_DIET_PROVENANCE = Provenance(
    source="Poore & Nemecek (2018), Science 360:181-184",
    basis="global median per meal",
    year=2018,
)

# --- Car ------------------------------------------------------------------
# Fleet-average CO2e per passenger-km, including well-to-tank where the source
# reports it. The global default is the DEFRA figure, which is built from SMMT
# registration data by market segment rather than from type-approval test values.
_CAR_KM_DEFAULT = 0.16984
_CAR_PROVENANCE_DEFAULT = Provenance(
    source="UK DEFRA / DESNZ greenhouse gas reporting conversion factors",
    basis="average car, petrol, fleet-weighted by SMMT registrations",
    year=2024,
)

# Per-region car factors, where a fleet-average figure for that region can be
# attributed. Deliberately sparse: a number with no source is worse than the
# default it would replace.
_CAR_KM_BY_REGION = {
    # EPA quotes a typical US passenger vehicle at 400 g CO2 per mile, which is
    # 0.2485 kg/km. Reported as CO2 rather than CO2e, and for a "typical" vehicle
    # rather than a fleet mean, so it is an upper-bound-ish stand-in.
    "us": 0.2485,
}
_CAR_PROVENANCE_BY_REGION = {
    "us": Provenance(
        source="US EPA, Greenhouse Gas Emissions from a Typical Passenger Vehicle",
        basis="typical passenger vehicle, CO2 not CO2e, 400 g/mile converted",
        year=None,
    ),
}

# --- Electricity ----------------------------------------------------------
# Grid carbon intensity, g CO2e/kWh, converted to kg below.
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
_GRID_PROVENANCE = Provenance(
    source="static reference values, representative national grid mixes",
    basis="annual average generation mix, g CO2e per kWh",
    year=None,
)

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


def car_factor(region):
    """kg CO2e per km for driving in `region`, and whether it is a real figure.

    Returns (value, is_default) so a caller can tell a measured number from the
    global stand-in. A region without its own figure is not wrong, it is just
    less precise, and the UI says which.
    """
    return (
        _CAR_KM_BY_REGION.get(region, _CAR_KM_DEFAULT),
        region not in _CAR_KM_BY_REGION,
    )


def car_factor_is_default(region):
    return car_factor(region)[1]


def car_provenance(region):
    if region in _CAR_KM_BY_REGION:
        return _CAR_PROVENANCE_BY_REGION[region]
    return _CAR_PROVENANCE_DEFAULT


def factors_for(region, travel_region=None):
    """Factor set for a region, falling back to the world average.

    travel_region is where the driving happened, which can differ from the home
    grid (a UK resident driving in France). Car travel is a fuel combustion
    figure rather than a grid figure, so it is driven by the travel region,
    while electricity uses the home region.
    """
    region = region if is_valid_region(region) else DEFAULT_REGION
    travel = travel_region if is_valid_region(travel_region) else region
    car_km, car_is_default = car_factor(travel)
    return {
        "region": region,
        "travel_region": travel,
        "factors_version": FACTORS_VERSION,
        "car_km": car_km,
        "car_km_is_default": car_is_default,
        "electricity_kwh": GRID_FACTORS_G_PER_KWH[region] / 1000.0,
        "meat_meal": _DIET["meat_meal"],
        "plant_meal": _DIET["plant_meal"],
    }


def snapshot(factors):
    """The subset stored on a Footprint row so history stays reproducible.

    Includes car_km_is_default: a later factor update may turn a fallback into a
    measured value, and the row has to keep saying which it was scored with.
    """
    return {
        "car_km": factors["car_km"],
        "car_km_is_default": factors.get("car_km_is_default", True),
        "electricity_kwh": factors["electricity_kwh"],
        "meat_meal": factors["meat_meal"],
        "plant_meal": factors["plant_meal"],
    }


def provenance_for(region):
    """Everything behind one region's numbers, for the API and the UI."""
    car_km, car_is_default = car_factor(region)
    return {
        "electricity_kwh": _GRID_PROVENANCE.to_dict(),
        "car_km": car_provenance(region).to_dict(),
        "car_km_is_default": car_is_default,
        "meat_meal": _DIET_PROVENANCE.to_dict(),
        "plant_meal": _DIET_PROVENANCE.to_dict(),
    }


def regions_with_measured_car_factor():
    """Regions whose car figure is measured rather than the global stand-in."""
    return sorted(_CAR_KM_BY_REGION)


def catalogue():
    """Everything the frontend needs to render labels and hints."""
    return {
        "default_region": DEFAULT_REGION,
        "factors_version": FACTORS_VERSION,
        "source": "static-reference",
        "regions": [
            {
                "code": code,
                "label": REGION_LABELS[code],
                "electricity_kwh": GRID_FACTORS_G_PER_KWH[code] / 1000.0,
                "car_km": car_factor(code)[0],
                "car_km_is_default": car_factor(code)[1],
                "provenance": provenance_for(code),
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
