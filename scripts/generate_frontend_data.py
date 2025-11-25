#!/usr/bin/env python3
"""
Generate paginated frontend data with on-demand loading.
Creates separate JSON files for each page (50 projects per page).

Views:
  1) All languages (GitHub-based SSR score)
  2) Python-only view with PyPI-enhanced score

GitHub score:
  - Heat (stars/forks/watchers) 70%
  - Quality (age/activity/health) 30%

Python+PyPI view:
  - 70% GitHub score
  - 30% binary PyPI signal (has PyPI package or not)
"""
import json
import os
import math
from collections import defaultdict
from datetime import datetime, timezone


# ============================================================
# Basic helpers
# ============================================================

def log_normalize(value, base=10):
    """Logarithmic normalization for better score distribution"""
    if value <= 0:
        return 0.0
    return math.log10(value + 1) / math.log10(base)


# ============================================================
# GitHub-based SSR scoring
# ============================================================

def age_factor(created_at):
    """
    Age factor in [0, 1].
    Mature projects (2–8 years) get higher scores.
    """
    try:
        created_time = datetime.strptime(
            created_at, "%Y-%m-%dT%H:%M:%SZ"
        ).replace(tzinfo=timezone.utc)
        years = (datetime.now(timezone.utc) - created_time).days / 365.25

        if years < 0.5:
            return 0.3  # too new
        elif years < 2:
            return 0.6 + (years - 0.5) * 0.2  # 0.6–0.9
        elif years < 5:
            return 0.9 + (years - 2) * 0.033  # 0.9–1.0 peak
        elif years < 8:
            return 1.0 - (years - 5) * 0.05   # 1.0–0.85
        else:
            return 0.7 - min((years - 8) * 0.03, 0.4)  # 0.7–0.3
    except Exception:
        return 0.5


def activity_factor(pushed_at, created_at):
    """
    Recent activity factor in [0, 1].
    Recent pushes indicate active maintenance.
    """
    try:
        pushed_time = datetime.strptime(
            pushed_at, "%Y-%m-%dT%H:%M:%SZ"
        ).replace(tzinfo=timezone.utc)
        created_time = datetime.strptime(
            created_at, "%Y-%m-%dT%H:%M:%SZ"
        ).replace(tzinfo=timezone.utc)

        days_since_push = (datetime.now(timezone.utc) - pushed_time).days
        project_age_days = (datetime.now(timezone.utc) - created_time).days

        if project_age_days < 1:
            return 1.0

        if days_since_push < 7:
            return 1.0
        elif days_since_push < 30:
            return 0.95
        elif days_since_push < 90:
            return 0.85
        elif days_since_push < 180:
            return 0.7
        elif days_since_push < 365:
            return 0.5
        else:
            return max(0.2, 0.5 - (days_since_push - 365) / 3650)
    except Exception:
        return 0.5


def health_factor(open_issues, stars):
    """
    Project health factor in [0, 1].
    Uses open issues relative to popularity (stars).
    """
    if stars < 10:
        return 1.0 if open_issues < 5 else 0.8

    issue_ratio = open_issues / (stars + 1)

    if issue_ratio < 0.01:
        return 1.0
    elif issue_ratio < 0.05:
        return 0.9
    elif issue_ratio < 0.1:
        return 0.8
    elif issue_ratio < 0.2:
        return 0.6
    else:
        return 0.4


def calculate_github_score(project):
    """
    Enhanced SSR GitHub score in [0, 10000].

    Base metrics (70% total, log-scaled):
      - Stars:    40%
      - Forks:    20%
      - Watchers: 10%

    Quality factors (30% total):
      - Age:      10%
      - Activity: 10%
      - Health:   10%
    """
    stars = project.get("stars", 0)
    forks = project.get("forks", 0)
    watchers = project.get("watchers", 0)
    open_issues = project.get("open_issues", 0)
    created_at = project.get("created_at", "2020-01-01T00:00:00Z")
    pushed_at = project.get("pushed_at", created_at)

    stars_score = log_normalize(stars, base=100000) * 0.40
    forks_score = log_normalize(forks, base=10000) * 0.20
    watchers_score = log_normalize(watchers, base=10000) * 0.10

    age_score = age_factor(created_at) * 0.10
    activity_score = activity_factor(pushed_at, created_at) * 0.10
    health_score = health_factor(open_issues, stars) * 0.10

    normalized_score = (
        stars_score
        + forks_score
        + watchers_score
        + age_score
        + activity_score
        + health_score
    )

    return int(normalized_score * 10000)


# ============================================================
# Language classification
# ============================================================

def classify_language(language):
    """Map raw GitHub language to a small set of categories."""
    if not language:
        return "Other"

    language_lower = language.lower()

    major_languages = {
        "javascript": "JavaScript",
        "typescript": "JavaScript",
        "python": "Python",
        "java": "Java",
        "c++": "C++",
        "c": "C++",
        "ruby": "Ruby",
        "go": "Go",
        "rust": "Rust",
        "swift": "Swift",
        "php": "PHP",
        "kotlin": "Kotlin",
    }

    return major_languages.get(language_lower, "Other")


# ============================================================
# PyPI-based scoring for Python projects
# ============================================================

def load_pypi_index(filename="data/seattle_pypi_projects.json"):
    """
    Build an index from seattle_pypi_projects.json:

        key:  "owner/repo"
        value: {
            "packages": [pkg1, pkg2, ...],
            "max_confidence": float in [0,1]
        }
    """
    if not os.path.exists(filename):
        print(f"⚠️ PyPI data file not found: {filename}")
        return {}

    with open(filename, "r") as f:
        data = json.load(f)

    projects = data.get("projects", [])
    index = {}

    for item in projects:
        url = item.get("url") or ""
        repo_full_name = None

        # Typical: https://github.com/owner/repo
        prefix = "https://github.com/"
        if url.startswith(prefix):
            parts = url[len(prefix):].split("/")
            if len(parts) >= 2:
                repo_full_name = parts[0] + "/" + parts[1]

        # Fallback: full_name
        if not repo_full_name:
            repo_full_name = item.get("full_name")

        # Fallback: owner + name
        if not repo_full_name:
            owner = item.get("owner")
            name = item.get("name")
            if owner and name:
                repo_full_name = f"{owner}/{name}"

        if not repo_full_name:
            continue

        entry = index.setdefault(
            repo_full_name,
            {"packages": set(), "max_confidence": 0.0},
        )

        pkg_name = item.get("name")
        if pkg_name:
            entry["packages"].add(pkg_name)

        conf = item.get("confidence", 0.0) or 0.0
        if conf > entry["max_confidence"]:
            entry["max_confidence"] = conf

    for repo, info in index.items():
        info["packages"] = sorted(list(info["packages"]))

    print(f"📦 PyPI index built for {len(index)} GitHub repos")
    return index


def calculate_pypi_score(pypi_info):
    """
    Binary PyPI score in [0, 1].

    - Has at least one PyPI package mapping → 1.0
    - Otherwise → 0.0
    """
    if not pypi_info:
        return 0.0

    num_packages = len(pypi_info.get("packages", []))
    if num_packages <= 0:
        return 0.0

    return 1.0


def calculate_python_project_score(base_score, pypi_info):
    """
    Only for Python main-language projects.

    overall_norm = 0.7 * github_norm + 0.3 * pypi_score
    """
    github_norm = base_score / 10000.0
    pypi_score = calculate_pypi_score(pypi_info)  # 0 or 1

    if pypi_score <= 0.0:
        return base_score

    final_norm = 0.7 * github_norm + 0.3 * pypi_score
    return int(final_norm * 10000)


# ============================================================
# Formatting helpers
# ============================================================

def format_project(project, score, extra=None):
    """Format project data for frontend."""
    data = {
        "name": project["name_with_owner"],
        "owner": project["owner"]["login"],
        "html_url": project["url"],
        "stars": project["stars"],
        "forks": project["forks"],
        "issues": project.get("open_issues", 0),
        "language": project.get("language", "Unknown"),
        "description": project.get("description", ""),
        "topics": project.get("topics", []),
        "score": score,
    }
    if extra:
        data.update(extra)
    return data


# ============================================================
# Main script
# ============================================================

def main():
    import sys
    from zoneinfo import ZoneInfo
    import glob
    import re

    PAGE_SIZE = 50

    # Select source data file
    if len(sys.argv) > 1:
        data_file = sys.argv[1]
    else:
        files = glob.glob("data/seattle_projects_*.json")
        if not files:
            print("❌ No project data files found in data/")
            return
        data_file = max(files)

    print(f"📂 Loading data from {data_file}...")
    with open(data_file, "r") as f:
        data = json.load(f)

    projects = data.get("projects", [])
    print(f"📦 Loaded {len(projects):,} projects")

    # Load PyPI mapping for Python projects
    pypi_index = load_pypi_index("data/seattle_pypi_projects.json")

    # Max values (for logging only)
    max_stars = max((p.get("stars", 0) for p in projects), default=1)
    max_forks = max((p.get("forks", 0) for p in projects), default=1)
    max_watchers = max((p.get("watchers", 0) for p in projects), default=1)

    print(
        f"📊 Max values: stars={max_stars:,}, "
        f"forks={max_forks:,}, watchers={max_watchers:,}"
    )

    # Compute scores and group by language
    by_language_all = defaultdict(list)
    python_pypi_list = []

    for project in projects:
        base_score = calculate_github_score(project)
        language_category = classify_language(project.get("language"))

        repo_key = project.get("name_with_owner")
        extra_fields = {
            "base_score": base_score,
        }

        # PyPI-enhanced score for Python view
        if language_category == "Python":
            pypi_info = pypi_index.get(repo_key)
            python_score = calculate_python_project_score(base_score, pypi_info)

            extra_fields["python_score"] = python_score
            extra_fields["has_pypi"] = bool(pypi_info)

            if pypi_info:
                extra_fields["pypi_packages"] = pypi_info.get("packages", [])
                extra_fields["pypi_max_confidence"] = pypi_info.get(
                    "max_confidence", 0.0
                )

            formatted_python = format_project(
                project, python_score, extra=extra_fields
            )
            python_pypi_list.append(formatted_python)

        # All-language view: use base GitHub score
        formatted_all = format_project(
            project, base_score, extra=extra_fields
        )
        by_language_all[language_category].append(formatted_all)

    # Sort lists
    for language in by_language_all:
        by_language_all[language].sort(
            key=lambda x: x["score"], reverse=True
        )

    python_pypi_list.sort(key=lambda x: x["score"], reverse=True)

    # Prepare output directories
    pages_dir = "frontend/public/pages"
    os.makedirs(pages_dir, exist_ok=True)

    pages_build_dir = "frontend/build/pages"
    os.makedirs(pages_build_dir, exist_ok=True)

    SEATTLE_TZ = ZoneInfo("America/Los_Angeles")

    # Extract date from filename (e.g., seattle_projects_20251120_220648.json)
    filename_match = re.search(r"(\d{8})_(\d{6})", data_file)
    if filename_match:
        date_str = filename_match.group(1)
        time_str = filename_match.group(2)
        data_datetime = datetime.strptime(
            f"{date_str}{time_str}", "%Y%m%d%H%M%S"
        )
        data_datetime = data_datetime.replace(
            tzinfo=timezone.utc
        ).astimezone(SEATTLE_TZ)
        last_updated = data_datetime.strftime("%Y-%m-%d %H:%M:%S %Z")
    else:
        last_updated = datetime.now(SEATTLE_TZ).strftime(
            "%Y-%m-%d %H:%M:%S %Z"
        )

    # ========================================================
    # 1) Metadata + pages for ALL languages
    # ========================================================
    metadata_all = {
        "languages": {},
        "page_size": PAGE_SIZE,
        "last_updated": last_updated,
    }

    total_all_projects = sum(len(v) for v in by_language_all.values())

    print(f"\n📊 Generating paginated data for ALL languages:")
    for language, lang_projects in sorted(
        by_language_all.items(), key=lambda x: len(x[1]), reverse=True
    ):
        total_projects = len(lang_projects)
        total_pages = (total_projects + PAGE_SIZE - 1) // PAGE_SIZE

        metadata_all["languages"][language] = {
            "total": total_projects,
            "pages": total_pages,
        }

        lang_dir = os.path.join(
            pages_dir, language.lower().replace("+", "plus")
        )
        os.makedirs(lang_dir, exist_ok=True)

        lang_build_dir = os.path.join(
            pages_build_dir, language.lower().replace("+", "plus")
        )
        os.makedirs(lang_build_dir, exist_ok=True)

        for page_num in range(total_pages):
            start_idx = page_num * PAGE_SIZE
            end_idx = min(start_idx + PAGE_SIZE, total_projects)
            page_data = lang_projects[start_idx:end_idx]

            page_file = os.path.join(
                lang_dir, f"page_{page_num + 1}.json"
            )
            with open(page_file, "w") as f:
                json.dump(page_data, f, separators=(",", ":"))

            build_page_file = os.path.join(
                lang_build_dir, f"page_{page_num + 1}.json"
            )
            with open(build_page_file, "w") as f:
                json.dump(page_data, f, separators=(",", ":"))

        percentage = (total_projects / total_all_projects * 100)
        print(
            f"  ✅ {language}: {total_projects:,} projects "
            f"({percentage:.1f}%) → {total_pages} pages"
        )

    metadata_file_all = "frontend/public/metadata.json"
    with open(metadata_file_all, "w") as f:
        json.dump(metadata_all, f, indent=2)

    with open("frontend/build/metadata.json", "w") as f:
        json.dump(metadata_all, f, indent=2)

    # ========================================================
    # 2) Python-only PyPI-enhanced view
    # ========================================================
    print("\n🐍 Generating Python+PyPI enhanced view:")

    python_total = len(python_pypi_list)
    python_pages = (python_total + PAGE_SIZE - 1) // PAGE_SIZE

    python_dir = os.path.join(pages_dir, "python_pypi")
    os.makedirs(python_dir, exist_ok=True)

    python_build_dir = os.path.join(pages_build_dir, "python_pypi")
    os.makedirs(python_build_dir, exist_ok=True)

    for page_num in range(python_pages):
        start_idx = page_num * PAGE_SIZE
        end_idx = min(start_idx + PAGE_SIZE, python_total)
        page_data = python_pypi_list[start_idx:end_idx]

        page_file = os.path.join(
            python_dir, f"page_{page_num + 1}.json"
        )
        with open(page_file, "w") as f:
            json.dump(page_data, f, separators=(",", ":"))

        build_page_file = os.path.join(
            python_build_dir, f"page_{page_num + 1}.json"
        )
        with open(build_page_file, "w") as f:
            json.dump(page_data, f, separators=(",", ":"))

    print(
        f"  ✅ Python+PyPI: {python_total:,} projects → {python_pages} pages"
    )

    metadata_python = {
        "language": "Python",
        "page_size": PAGE_SIZE,
        "last_updated": last_updated,
        "total": python_total,
        "pages": python_pages,
        "view": "python_pypi",
        "description": (
            "Python projects ranked with GitHub metrics (70%) "
            "and binary PyPI presence (30%)."
        ),
    }

    metadata_python_file = "frontend/public/metadata_python_pypi.json"
    with open(metadata_python_file, "w") as f:
        json.dump(metadata_python, f, indent=2)

    with open("frontend/build/metadata_python_pypi.json", "w") as f:
        json.dump(metadata_python, f, indent=2)

    # ========================================================
    # Summary
    # ========================================================
    print(f"\n✅ Saved metadata (ALL) to {metadata_file_all}")
    print(f"✅ Saved metadata (Python+PyPI) to {metadata_python_file}")
    print(
        f"\n🎉 Done! Generated {sum(m['pages'] for m in metadata_all['languages'].values())} "
        f"language-page files + {python_pages} Python+PyPI pages"
    )
    print(
        f"   Each page contains up to {PAGE_SIZE} projects"
    )
    print(
        f"   Total size (all languages): ~{sum(m['total'] for m in metadata_all['languages'].values()):,} projects"
    )
    print(f"   Python+PyPI projects: {python_total:,}")


if __name__ == "__main__":
    main()