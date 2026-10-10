RISK_BANDS = [
    {"max": 4, "code": "L", "name": "Low", "color": "#C6EFCE"},
    {"max": 9, "code": "M", "name": "Medium", "color": "#FFFF80"},
    {"max": 16, "code": "H", "name": "High", "color": "#FFC000"},
    {"max": 25, "code": "VH", "name": "Very High", "color": "#FF7C80"},
]

SEVERITY = [
    {"level": 1, "name": "Minor", "desc": "First aid injury; negligible release; minimal production impact"},
    {"level": 2, "name": "Moderate", "desc": "Medical treatment / restricted work; minor release; short production loss"},
    {"level": 3, "name": "Serious", "desc": "Lost time injury; contained release; equipment damage / significant production loss"},
    {"level": 4, "name": "Major", "desc": "Permanent disability or single fatality; significant release / fire"},
    {"level": 5, "name": "Catastrophic", "desc": "Multiple fatalities; major fire / explosion; major environmental damage"},
]

LIKELIHOOD = [
    {"level": 1, "name": "Remote", "desc": "Not expected in facility life (< 1E-4 /yr)"},
    {"level": 2, "name": "Unlikely", "desc": "Could occur in facility life (1E-4 to 1E-3 /yr)"},
    {"level": 3, "name": "Possible", "desc": "Has occurred in industry (1E-3 to 1E-2 /yr)"},
    {"level": 4, "name": "Likely", "desc": "Has occurred at company sites (1E-2 to 1E-1 /yr)"},
    {"level": 5, "name": "Frequent", "desc": "Expected to occur several times (> 1E-1 /yr)"},
]


def band(score):
    for b in RISK_BANDS:
        if score <= b["max"]:
            return b
    return RISK_BANDS[-1]


def evaluate(c, l):
    c, l = max(1, min(5, int(c))), max(1, min(5, int(l)))
    b = band(c * l)
    return {"score": c * l, "code": b["code"], "name": b["name"], "color": b["color"]}


def matrix():
    return {"bands": RISK_BANDS, "severity": SEVERITY, "likelihood": LIKELIHOOD}
