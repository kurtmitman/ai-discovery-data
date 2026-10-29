#!/usr/bin/env python3
"""A stock-flow model of vulnerability discovery, calibrated to curl.

Run: python3 analysis/depletion/model.py   (needs numpy and matplotlib)

Latent bugs of vintage v (the day the introducing commit landed) enter at rate
kappa * c(v), where c is curl's commits per year. Each latent bug is found with
hazard lambda(t) and disappears unfound, when its code is rewritten, at rate
delta. Discoveries are D(t) = lambda(t) * S(t). Under a constant pre-AI hazard
lambda0, the vintage of a bug found at t has density proportional to
c(v) * exp(-(lambda0 + delta) * (t - v)), which identifies theta = lambda0 +
delta from disclosure ages alone; the pre-AI count of disclosures then scales
kappa * lambda0. delta is not identified and is set by assumption.

Reads curl-bug-ages.csv and curl-commits-by-year.csv (built by curl_ages.py),
and problems/cyber-openssl/openssl-cves.csv for the cross-check table. Writes
the four depletion-*.png figures beside this file and prints every number the
README quotes. These PNGs are not part of the pinned figure pipeline.
"""

from __future__ import annotations

import csv
import re
import sys
from collections import Counter
from datetime import date
from pathlib import Path

import matplotlib
import matplotlib.ticker

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))

from lib.palette import AI, HUMAN, NEUTRAL, VENDOR  # noqa: E402

STEP = 1 / 52                      # simulation step, years
IMPORT_COMMIT = "ae1912cb0d494b48d514d937826c9fe83ec96c4d"  # "Initial revision"
PRE_AI = (2010.0, 2025.0)          # disclosures used to estimate the pre-AI hazard
START = 2010.0                     # forward simulation starts here
DELTAS = (0.0, 0.05)               # rewrite rate of latent bugs, by assumption
HORIZON = 2031.0


def year_fraction(iso: str) -> float:
    d = date.fromisoformat(iso)
    days = (date(d.year + 1, 1, 1) - date(d.year, 1, 1)).days
    return d.year + (d.timetuple().tm_yday - 0.5) / days


def load():
    with (HERE / "curl-bug-ages.csv").open(newline="", encoding="utf-8") as fh:
        bugs = list(csv.DictReader(fh))
    with (HERE / "curl-commits-by-year.csv").open(newline="", encoding="utf-8") as fh:
        commit_rows = list(csv.DictReader(fh))
    commits = {}
    for row in commit_rows:
        n = int(row["commits"])
        if row["partial_year"] == "yes":
            n = n / (year_fraction(row["data_through"]) - int(row["year"]))
        commits[int(row["year"])] = float(n)
    pub = np.array([year_fraction(b["published"]) for b in bugs])
    born = pub - np.array([float(b["age_years"]) for b in bugs])
    lump = np.array([b["introduced_commit"] == IMPORT_COMMIT for b in bugs])
    ai = np.array([b["ai_marker"] == "yes" for b in bugs])
    v0 = year_fraction("1999-12-29")
    return bugs, commits, pub, born, lump, ai, v0


class Inflow:
    """Commits per year as a step function of time, with a chosen future."""

    def __init__(self, commits: dict[int, float], future: float):
        self.commits = commits
        self.last = max(commits)
        self.future = future

    def __call__(self, t: np.ndarray | float) -> np.ndarray:
        years = np.floor(np.asarray(t, dtype=float)).astype(int)
        out = np.array([
            self.commits.get(y, 0.0) if y <= self.last else self.future
            for y in np.atleast_1d(years)
        ])
        return out


# --- Pre-AI hazard: conditional likelihood of vintage given disclosure date ---

def estimate_theta(c: Inflow, pub, born, lump, v0):
    """Grid MLE of theta = lambda0 + delta and W, the import commit's weight.

    The 1999-12-29 "Initial revision" commit imports all of curl 6.3.1 at once,
    so bugs blamed on it are a point mass whose weight W (in commit-equivalents)
    is estimated alongside theta.
    """
    sel = (pub >= PRE_AI[0]) & (pub < PRE_AI[1])
    t, v, is_lump = pub[sel], born[sel], lump[sel]
    grid = np.arange(v0 + STEP / 2, PRE_AI[1], STEP)
    cg = c(grid) * STEP
    thetas = np.linspace(0.02, 0.50, 241)
    weights = np.geomspace(50, 2e5, 161)
    loglik = np.empty((thetas.size, weights.size))
    for i, th in enumerate(thetas):
        kernel = np.where(grid[None, :] < t[:, None],
                          np.exp(-th * (t[:, None] - grid[None, :])), 0.0)
        b = kernel @ cg                         # vintages after the import
        a = np.exp(-th * (t - v0))              # the import lump, per unit W
        num_density = np.where(is_lump, 0.0,
                               np.log(np.maximum(c(v), 1e-12)) - th * (t - v))
        for j, w in enumerate(weights):
            z = w * a + b
            num = np.where(is_lump, np.log(w) - th * (t - v0), num_density)
            loglik[i, j] = np.sum(num - np.log(z))
    i, j = np.unravel_index(np.argmax(loglik), loglik.shape)
    profile = loglik.max(axis=1)
    inside = thetas[profile >= profile.max() - 1.92]
    return {
        "theta": thetas[i], "W": weights[j], "ci": (inside.min(), inside.max()),
        "n": int(sel.sum()),
    }


def latent_index(c: Inflow, theta: float, W: float, v0: float, t: np.ndarray):
    """X(t): latent stock in commit units under the constant pre-AI hazard."""
    grid = np.arange(v0 + STEP / 2, t.max(), STEP)
    kernel = np.where(grid[None, :] < t[:, None],
                      np.exp(-theta * (t[:, None] - grid[None, :])), 0.0)
    return W * np.exp(-theta * (t - v0)) + kernel @ (c(grid) * STEP)


# --- Forward simulation with the observed disclosures ---------------------------

class Stock:
    """Latent bugs by vintage, depleted uniformly (proportional hazard)."""

    def __init__(self, c: Inflow, kappa, theta, W, v0, start):
        self.c, self.kappa = c, kappa
        self.grid = np.arange(v0 + STEP / 2, HORIZON + STEP, STEP)
        self.v0 = v0
        past = self.grid < start
        self.cells = np.where(
            past, kappa * c(self.grid) * STEP * np.exp(-theta * (start - self.grid)), 0.0
        )
        self.lump = kappa * W * np.exp(-theta * (start - v0))
        self.t = start

    def total(self) -> float:
        return self.cells.sum() + self.lump

    def advance(self, until: float, lam: float, delta: float, dry: bool = False):
        """Run to `until` at hazard lam; return (found, exposure = integral of S)."""
        cells, lump, t = self.cells.copy(), self.lump, self.t
        found = exposure = 0.0
        while t < until - 1e-9:
            h = min(STEP, until - t)
            k = int(np.searchsorted(self.grid, t + h / 2) - 0)
            k = min(max(k, 0), cells.size - 1)
            cells[k] += self.kappa * float(self.c(t + h / 2)[0]) * h
            s = cells.sum() + lump
            rate = lam + delta
            keep = np.exp(-rate * h)
            gone = s * (1 - keep)
            found += lam / rate * gone if rate > 0 else 0.0
            exposure += gone / rate if rate > 0 else s * h
            cells *= keep
            lump *= keep
            t += h
        if not dry:
            self.cells, self.lump, self.t = cells, lump, t
        return found, exposure

    def hazard_for(self, until: float, count: int, delta: float) -> float:
        """The constant hazard over (t, until] that finds exactly `count` bugs."""
        if count == 0:
            return 0.0
        lo, hi = 0.0, 1.0
        while self.advance(until, hi, delta, dry=True)[0] < count:
            hi *= 2
            if hi > 1e4:
                return float("inf")
        for _ in range(60):
            mid = (lo + hi) / 2
            if self.advance(until, mid, delta, dry=True)[0] < count:
                lo = mid
            else:
                hi = mid
        return (lo + hi) / 2

    def vintage_density(self):
        """Current latent stock by vintage (lump reported separately)."""
        return self.grid, self.cells.copy(), self.lump


def simulate_history(c, kappa, theta, W, v0, delta, pub):
    """Replay the observed disclosure batches from START, solving the hazard
    between consecutive batch dates. Returns per-interval hazards, annual
    hazards, the stock at the last batch, and each 2026 bug's predicted vintage
    density at its disclosure date."""
    stock = Stock(c, kappa, theta, W, v0, START)
    batches = Counter(np.round(pub[pub >= START], 6))
    intervals, density_at = [], {}
    annual_found, annual_exposure = Counter(), Counter()
    for when in sorted(batches):
        start = stock.t
        n = batches[when]
        lam = stock.hazard_for(when, n, delta)
        found, exposure = stock.advance(when, lam, delta)
        intervals.append((start, when, n, lam, exposure))
        # attribute exposure to calendar years in proportion to elapsed time
        y0, y1 = int(np.floor(start)), int(np.floor(when))
        for y in range(y0, y1 + 1):
            share = (min(when, y + 1) - max(start, y)) / (when - start)
            annual_exposure[y] += exposure * share
        annual_found[int(np.floor(when))] += n
        if when >= 2025.0:
            # depletion is uniform across vintages, so the stock left at the
            # batch has the same vintage shape as the stock the batch came from
            density_at[when] = stock.vintage_density()
    annual = {y: annual_found[y] / annual_exposure[y] for y in sorted(annual_exposure)
              if annual_exposure[y] > 0}
    return intervals, annual, stock, density_at


def project(stock: Stock, lam_path, delta: float, until: float = HORIZON):
    """Annual discoveries after the last batch for a hazard path lam_path(t)."""
    out = Counter()
    t = stock.t
    while t < until - 1e-9:
        h = min(STEP, until - t)
        found, _ = stock.advance(t + h, lam_path(t), delta)
        out[int(np.floor(t))] += found
        t = stock.t
    return out


# --- Age test ----------------------------------------------------------------------

def age_test(c, v0, theta, W, delta, density_at, pub, born, lump, mask):
    """Log-likelihood of observed 2026 vintages under the proportional-hazard
    stock (H) and under a never-reached segment (U) whose stock only decays at
    delta; returns the MLE mixture weight on U with its profile interval."""
    sel = np.where(mask)[0]
    log_h, log_u = [], []
    for i in sel:
        key = min(density_at, key=lambda k: abs(k - pub[i]))
        grid, cells, lp = density_at[key]
        total = cells.sum() + lp
        if lump[i]:
            ph = lp / total
        else:
            k = np.clip(np.searchsorted(grid, born[i]), 0, grid.size - 1)
            ph = cells[k] / STEP / total
        ug = grid[grid < pub[i]]
        u_cells = c(ug) * STEP * np.exp(-delta * (pub[i] - ug))
        u_lump = W * np.exp(-delta * (pub[i] - v0))
        u_total = u_cells.sum() + u_lump
        if lump[i]:
            pu = u_lump / u_total
        else:
            pu = float(c(born[i])[0]) * np.exp(-delta * (pub[i] - born[i])) / u_total
        log_h.append(np.log(max(ph, 1e-300)))
        log_u.append(np.log(max(pu, 1e-300)))
    log_h, log_u = np.array(log_h), np.array(log_u)
    ws = np.linspace(0, 1, 201)
    ll = np.array([np.sum(np.logaddexp(np.log1p(-w + 1e-12) + log_h,
                                       np.log(w + 1e-12) + log_u)) for w in ws])
    inside = ws[ll >= ll.max() - 1.92]
    return {"w": ws[np.argmax(ll)], "ci": (inside.min(), inside.max()),
            "n": len(sel), "ll_h": log_h.sum(), "ll_u": log_u.sum()}


def predicted_ages(c, v0, W, delta, density_at, when):
    """Median age of the H stock and of the U segment at date `when`."""
    key = min(density_at, key=lambda k: abs(k - when))
    grid, cells, lp = density_at[key]
    def median(ages, mass):
        order = np.argsort(ages)
        cum = np.cumsum(mass[order]) / mass.sum()
        return ages[order][np.searchsorted(cum, 0.5)]
    ages_h = np.append(when - grid[grid < when], when - v0)
    mass_h = np.append(cells[grid < when], lp)
    ug = grid[grid < when]
    ages_u = np.append(when - ug, when - v0)
    mass_u = np.append(c(ug) * STEP * np.exp(-delta * (when - ug)),
                       W * np.exp(-delta * (when - v0)))
    return median(ages_h, mass_h), median(ages_u, mass_u), (ages_h, mass_h, ages_u, mass_u)


# --- OpenSSL cross-check --------------------------------------------------------

# First release of each OpenSSL line, month precision (openssl.org release history).
OPENSSL_LINES = {
    "0.9.6": "2000-09-24", "0.9.7": "2002-12-31", "0.9.8": "2005-07-05",
    "1.0.0": "2010-03-29", "1.0.1": "2012-03-14", "1.0.2": "2015-01-22",
    "1.1.0": "2016-08-25", "1.1.1": "2018-09-11", "3.0": "2021-09-07",
    "3.1": "2023-03-14", "3.2": "2023-11-23", "3.3": "2024-04-09",
    "3.4": "2024-10-22", "3.5": "2025-04-08", "3.6": "2025-10-01",
    "4.0": "2026-04-15",
}


def openssl_table():
    path = ROOT / "problems" / "cyber-openssl" / "openssl-cves.csv"
    with path.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    out = {}
    for r in rows:
        year = int(r["published"][:4])
        if year < 2021:
            continue
        lines = []
        for v in re.findall(r"(\d+\.\d+\.\d+)[a-z]*\s+to", r["affected_versions"]):
            parts = v.split(".")
            key = ".".join(parts[:2]) if parts[0] in ("3", "4") else v
            if key in OPENSSL_LINES:
                lines.append(year_fraction(OPENSSL_LINES[key]))
        if not lines:
            continue
        out.setdefault(year, []).append(
            (year_fraction(r["published"]) - min(lines), "1.0.2" in r["affected_versions"])
        )
    return {y: (len(v), float(np.median([a for a, _ in v])),
                sum(o for _, o in v) / len(v)) for y, v in sorted(out.items())}


# --- Figures -------------------------------------------------------------------------

def style(ax, integer_years: bool = False):
    if integer_years:
        ax.xaxis.set_major_locator(matplotlib.ticker.MaxNLocator(integer=True))
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", color="#e6e6e6", linewidth=0.8)
    ax.set_axisbelow(True)


def fig_mechanics(lam0: float):
    """Discovery flow after a one-time hazard jump, and after a rising hazard."""
    t = np.arange(-2, 8, 0.01)
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.6))
    for k, shade in zip((2, 5, 10), ("#9db7d9", "#4f7fbf", "#1f3f73")):
        lam1 = k * lam0
        flow = np.where(t < 0, 1.0, k * np.exp(-lam1 * np.clip(t, 0, None))
                        + (1 - np.exp(-lam1 * np.clip(t, 0, None))))
        axes[0].plot(t, flow, color=shade, label=f"hazard × {k}")
        excess = np.where(t < 0, 0.0, (1 - 1 / k) * (1 - np.exp(-lam1 * np.clip(t, 0, None))))
        axes[1].plot(t, excess / lam0, color=shade, label=f"hazard × {k}")
    axes[0].axhline(1, color=NEUTRAL, linewidth=0.8, linestyle="--")
    axes[0].set_ylabel("discoveries / inflow")
    axes[0].set_title("Flow: spike, then back to the inflow", fontsize=10, loc="left")
    axes[1].set_ylabel("extra discoveries / inflow (years of inflow)")
    axes[1].set_title("Cumulative excess: a level shift = the backlog", fontsize=10,
                      loc="left")
    for ax in axes:
        ax.axvline(0, color=VENDOR, linewidth=0.8)
        ax.set_xlabel("years since the hazard jump")
        ax.legend(frameon=False, fontsize=8)
        style(ax)
    fig.suptitle(f"One-time jump in search hazard from λ₀ = {lam0:.2f}/yr, no rewriting (δ = 0)",
                 fontsize=10)
    fig.tight_layout()
    fig.savefig(HERE / "depletion-mechanics.png", dpi=150)
    plt.close(fig)


def fig_hazard(pub, ai, intervals, annual, lam0, fitted):
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.8))
    years = np.arange(2010, 2027)
    counts = Counter(np.floor(pub).astype(int))
    ai_counts = Counter(np.floor(pub[ai]).astype(int))
    axes[0].bar(years, [counts[y] - ai_counts[y] for y in years], color=HUMAN,
                label="no AI marker")
    axes[0].bar(years, [ai_counts[y] for y in years],
                bottom=[counts[y] - ai_counts[y] for y in years], color=AI,
                label="AI marker")
    axes[0].plot(sorted(fitted), [fitted[y] for y in sorted(fitted)], color="black",
                 linewidth=1.2, label="model, pre-AI hazard")
    axes[0].set_title("curl CVEs per year (2026 through Oct 14)", fontsize=10, loc="left")
    axes[0].legend(frameon=False, fontsize=8)
    ys = [y for y in annual if 2014 <= y <= 2025]
    axes[1].plot([y + 0.5 for y in ys], [annual[y] for y in ys], "o-", color=HUMAN,
                 markersize=4,
                 label="annual, implied")
    recent = [iv for iv in intervals if iv[1] >= 2025.6]
    for a, b, n, lam, _ in recent:
        axes[1].plot([a, b], [lam, lam], color=AI, linewidth=2.2)
    axes[1].plot([], [], color=AI, linewidth=2.2, label="between 2025–26 releases")
    axes[1].axhline(lam0, color=NEUTRAL, linestyle="--", linewidth=0.8,
                    label=f"λ₀ = {lam0:.2f}")
    axes[1].set_yscale("log")
    axes[1].set_title("Implied search hazard D/S (per year, log)", fontsize=10, loc="left")
    axes[1].legend(frameon=False, fontsize=8)
    for ax in axes:
        style(ax, integer_years=True)
    fig.tight_layout()
    fig.savefig(HERE / "depletion-curl-hazard.png", dpi=150)
    plt.close(fig)


def fig_ages(pub, born, ai, pred):
    ages = pub - born
    fig, ax = plt.subplots(figsize=(6.4, 4))
    def ecdf(x, **kw):
        x = np.sort(x)
        ax.step(x, np.arange(1, x.size + 1) / x.size, where="post", **kw)
    pre = (pub >= 2016) & (pub < 2025)
    ecdf(ages[pre], color=NEUTRAL, linewidth=2, label=f"2016–24 disclosures (n={pre.sum()})")
    m26 = pub >= 2026
    ecdf(ages[m26 & ai], color=AI, linewidth=1.8,
         label=f"2026, AI marker (n={(m26 & ai).sum()})")
    ecdf(ages[m26 & ~ai], color=HUMAN, linewidth=1.8,
         label=f"2026, no AI marker (n={(m26 & ~ai).sum()})")
    ages_h, mass_h, ages_u, mass_u = pred
    for a, m, ls, lab in ((ages_h, mass_h, "--", "model: scaled-up search (H)"),
                          (ages_u, mass_u, ":", "model: never-reached segment (U)")):
        o = np.argsort(a)
        ax.plot(a[o], np.cumsum(m[o]) / m.sum(), color="black", linestyle=ls,
                linewidth=1.2, label=lab)
    ax.set_xlabel("age of the bug at disclosure (years since introducing commit)")
    ax.set_ylabel("share of disclosures")
    ax.set_xlim(0, 27)
    ax.legend(frameon=False, fontsize=8, loc="lower right")
    style(ax)
    fig.tight_layout()
    fig.savefig(HERE / "depletion-curl-ages.png", dpi=150)
    plt.close(fig)


def fig_scenarios(pub, scenarios, ceiling_lo, ceiling_hi):
    fig, ax = plt.subplots(figsize=(7.2, 4))
    years = np.arange(2010, 2026)
    counts = Counter(np.floor(pub).astype(int))
    ax.bar(years, [counts[y] for y in years], color="#d0d7e2", label="observed")
    observed_2026 = counts[2026] / (year_fraction("2026-10-14") - 2026)
    ax.bar([2026], [observed_2026], color="#d0d7e2", hatch="///", edgecolor="white",
           label="2026 annualized")
    for label, (series, color, ls) in scenarios.items():
        ys = sorted(series)
        ax.plot(ys, [series[y] for y in ys], color=color, linestyle=ls, marker="o",
                markersize=3, label=label)
    ax.axhspan(ceiling_lo, ceiling_hi, color=NEUTRAL, alpha=0.18,
               label="long-run ceiling: every new bug found")
    ax.set_ylabel("curl CVEs per year")
    ax.set_xlim(2009.5, HORIZON - 0.5)
    ax.set_title("Discoveries after the harvest (δ = 0, inflow at the 2025–26 commit "
                 "rate unless noted)", fontsize=10, loc="left")
    ax.legend(frameon=False, fontsize=7.5, loc="upper left")
    style(ax, integer_years=True)
    fig.tight_layout()
    fig.savefig(HERE / "depletion-curl-scenarios.png", dpi=150)
    plt.close(fig)


# --- Sensitivity -----------------------------------------------------------------

def flat_inflow_check(commits, pub, born, lump, ai, v0):
    """Re-run the delta = 0 calibration with the inflow held at its 2014–23 mean
    from 2024 on. curl's commit count doubled over 2024–26, partly with fixes for
    the very reports being modelled, so commits may overstate new latent bugs,
    and the inflow sets how young the model expects 2026's bugs to be."""
    base = np.mean([commits[y] for y in range(2014, 2024)])
    c = Inflow({y: (base if y >= 2024 else n) for y, n in commits.items()}, future=base)
    est = estimate_theta(c, pub, born, lump, v0)
    theta, W = est["theta"], est["W"]
    pre_t = np.arange(PRE_AI[0] + STEP / 2, PRE_AI[1], STEP)
    n_pre = int(((pub >= PRE_AI[0]) & (pub < PRE_AI[1])).sum())
    kappa = n_pre / (latent_index(c, theta, W, v0, pre_t).sum() * STEP) / theta
    intervals, _, stock, density_at = simulate_history(c, kappa, theta, W, v0, 0.0, pub)
    S_2026 = kappa * latent_index(c, theta, W, v0, np.array([2026.0]))[0]
    recent = [iv for iv in intervals if iv[1] >= year_fraction("2026-06-24")]
    lam_recent = sum(iv[2] for iv in recent) / sum(iv[4] for iv in recent)
    print(f"\nflat inflow from 2024 ({base:.0f} commits/yr), delta = 0: theta = "
          f"{theta:.3f}/yr (95% {est['ci'][0]:.3f}–{est['ci'][1]:.3f}); latent stock "
          f"2026-01-01 = {S_2026:.0f}; pooled hazard Jun 24–Oct 14 2026 = "
          f"{lam_recent:.2f}/yr ({lam_recent / theta:.1f}× λ0)")
    med_h, med_u, _ = predicted_ages(c, v0, W, 0.0, density_at, year_fraction("2026-06-24"))
    print(f"  predicted median age mid-2026: H {med_h:.1f}y, U {med_u:.1f}y")
    for label, mask in (("all 2026", pub >= 2026),
                        ("2026 AI marker", (pub >= 2026) & ai),
                        ("2026 no AI marker", (pub >= 2026) & ~ai)):
        at = age_test(c, v0, theta, W, 0.0, density_at, pub, born, lump, mask)
        print(f"  age test, {label:18s} n={at['n']:2d}: weight on never-reached "
              f"segment {at['w']:.2f} (95% {at['ci'][0]:.2f}–{at['ci'][1]:.2f})")
    proj = project(stock, lambda t: lam_recent, 0.0)
    proj[2026] += int((pub >= 2026).sum())
    print("  hold: " + "  ".join(f"{y}: {proj[y]:5.1f}" for y in range(2026, 2031)))


# --- Main ----------------------------------------------------------------------------

def main() -> None:
    bugs, commits, pub, born, lump, ai, v0 = load()
    recent_rate = np.mean([commits[2025], commits[2026]])
    decade_rate = np.mean([commits[y] for y in range(2010, 2020)])
    c = Inflow(commits, future=recent_rate)
    print(f"commits/yr: 2010–19 mean {decade_rate:.0f}; 2025–26 mean {recent_rate:.0f}")

    est = estimate_theta(c, pub, born, lump, v0)
    theta, W = est["theta"], est["W"]
    print(f"theta = lambda0 + delta = {theta:.3f}/yr (95% {est['ci'][0]:.3f}–"
          f"{est['ci'][1]:.3f}), import weight W = {W:.0f} commit-equivalents, "
          f"n = {est['n']}")

    pre_t = np.arange(PRE_AI[0] + STEP / 2, PRE_AI[1], STEP)
    X = latent_index(c, theta, W, v0, pre_t)
    n_pre = int(((pub >= PRE_AI[0]) & (pub < PRE_AI[1])).sum())
    A = n_pre / (X.sum() * STEP)                     # = kappa * lambda0
    fit_t = np.arange(2010 + STEP / 2, 2026, STEP)
    Xf = latent_index(c, theta, W, v0, fit_t)
    fitted = {y: A * Xf[(fit_t >= y) & (fit_t < y + 1)].sum() * STEP
              for y in range(2010, 2026)}
    print(f"pre-AI fit: {n_pre} disclosures 2010–24; model {min(fitted.values()):.1f}–"
          f"{max(fitted.values()):.1f}/yr over 2010–25")

    results = {}
    for delta in DELTAS:
        lam0 = theta - delta
        kappa = A / lam0
        intervals, annual, stock, density_at = simulate_history(
            c, kappa, theta, W, v0, delta, pub)
        S_2026 = kappa * latent_index(c, theta, W, v0, np.array([2026.0]))[0]
        found_2026 = int((pub >= 2026).sum())
        recent = [iv for iv in intervals if iv[1] >= year_fraction("2026-06-24")]
        lam_recent = sum(iv[2] for iv in recent) / sum(iv[4] for iv in recent)
        S_now = stock.total()
        res = {"lam0": lam0, "kappa": kappa, "S_2026": S_2026, "found_2026": found_2026,
               "S_now": S_now, "lam_recent": lam_recent, "intervals": intervals,
               "annual": annual, "density_at": density_at}
        # scenarios from the last batch
        scen = {}
        for name, lam_path, future in (
            ("hold", lambda t: lam_recent, recent_rate),
            ("hold, 2010s inflow", lambda t: lam_recent, decade_rate),
            ("double yearly", lambda t: lam_recent * 2 ** (t - stock.t), recent_rate),
            ("back to λ₀", lambda t: lam0, recent_rate),
        ):
            s = Stock(Inflow(commits, future), kappa, theta, W, v0, START)
            s.cells, s.lump, s.t = stock.cells.copy(), stock.lump, stock.t
            s.c = Inflow(commits, future)
            proj = project(s, lam_path, delta)
            proj[2026] += found_2026
            scen[name] = proj
        res["scenarios"] = scen
        res["ceiling"] = (kappa * decade_rate, kappa * recent_rate)
        results[delta] = res
        print(f"\ndelta = {delta:.2f}: lambda0 = {lam0:.3f}/yr, kappa = {kappa*1000:.2f} bugs"
              f" per 1000 commits; human find share = {lam0/theta:.0%}")
        print(f"  latent stock 2026-01-01 = {S_2026:.0f}; found in 2026 = {found_2026} "
              f"({found_2026/S_2026:.0%} of it); left after Oct 14 = {S_now:.0f}")
        print("  hazard between batches since 2025-09: " + ", ".join(
            f"{iv[1]:.2f}: {iv[2]} → {iv[3]:.2f}" for iv in intervals if iv[1] >= 2025.6))
        print(f"  pooled hazard Jun 24–Oct 14 2026 = {lam_recent:.2f}/yr "
              f"({lam_recent/lam0:.1f}× λ0); half-life of excess "
              f"{np.log(2)/(lam_recent+delta)*12:.1f} months")
        print("  annual implied hazard 2016–25: " + ", ".join(
            f"{y}: {annual[y]:.2f}" for y in range(2016, 2026)))
        for name, proj in scen.items():
            print(f"  {name:20s}" + "  ".join(f"{y}: {proj[y]:5.1f}"
                                              for y in range(2026, 2031)))
        print(f"  ceiling (all new bugs found): {res['ceiling'][0]:.1f}/yr at 2010s "
              f"inflow, {res['ceiling'][1]:.1f}/yr at 2025–26 inflow; pre-AI steady "
              f"state {lam0/theta*res['ceiling'][0]:.1f}/yr")

        for label, mask in (("all 2026", pub >= 2026),
                            ("2026 AI marker", (pub >= 2026) & ai),
                            ("2026 no AI marker", (pub >= 2026) & ~ai)):
            at = age_test(c, v0, theta, W, delta, density_at, pub, born, lump, mask)
            print(f"  age test, {label:18s} n={at['n']:2d}: weight on never-reached "
                  f"segment {at['w']:.2f} (95% {at['ci'][0]:.2f}–{at['ci'][1]:.2f})")
        med_h, med_u, pred = predicted_ages(c, v0, W, delta, density_at,
                                            year_fraction("2026-06-24"))
        res["pred"] = pred
        print(f"  predicted median age mid-2026: H {med_h:.1f}y, U {med_u:.1f}y")

    ages = pub - born
    for label, mask in (("2016–24", (pub >= 2016) & (pub < 2025)),
                        ("2026 all", pub >= 2026), ("2026 AI", (pub >= 2026) & ai),
                        ("2026 other", (pub >= 2026) & ~ai)):
        a = ages[mask]
        print(f"observed {label:10s} n={a.size:3d} median {np.median(a):4.1f}y "
              f"mean {a.mean():4.1f}y  >10y {np.mean(a > 10):.0%}")
    for y in range(2014, 2027):
        a = ages[np.floor(pub).astype(int) == y]
        print(f"  {y}: n={a.size:2d} median {np.median(a):4.1f}y mean {a.mean():4.1f}y "
              f">10y {np.mean(a > 10):.0%}")
    print("\nOpenSSL, oldest affected line (lower-bound age):")
    for y, (n, med, share) in openssl_table().items():
        print(f"  {y}: n={n:2d} median {med:4.1f}y  reaches 1.0.2 {share:.0%}")
    flat_inflow_check(commits, pub, born, lump, ai, v0)

    base = results[0.0]
    fig_mechanics(base["lam0"])
    fig_hazard(pub, ai, base["intervals"], base["annual"], base["lam0"], fitted)
    fig_ages(pub, born, ai, base["pred"])
    colors = {"hold": (AI, "-"), "hold, 2010s inflow": (AI, "--"),
              "double yearly": ("#7a1f12", ":"), "back to λ₀": (HUMAN, "-")}
    labels = {"hold": "hazard holds at its 2026 level",
              "hold, 2010s inflow": "… with inflow back at the 2010s commit rate",
              "double yearly": "hazard keeps doubling every year",
              "back to λ₀": "hazard falls back to λ₀"}
    fig_scenarios(pub, {labels[k]: (v, *colors[k]) for k, v in base["scenarios"].items()},
                  *base["ceiling"])
    print("\nwrote depletion-mechanics.png, depletion-curl-hazard.png, "
          "depletion-curl-ages.png, depletion-curl-scenarios.png")


if __name__ == "__main__":
    main()
