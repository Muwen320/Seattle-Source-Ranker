#!/usr/bin/env python3
"""
Generate paginated frontend data with on-demand loading.
Creates separate JSON files for each page (50 projects per page by default).
Uses enhanced SSR scoring algorithm with multiple factors.
"""

import json
import os
import math
from collections import defaultdict
from datetime import datetime, timezone

# Page size can be overridden via environment variable SSR_PAGE_SIZE
PAGE_SIZE = int(os.getenv("SSR_PAGE_SIZE", "50"))


def log_normalize(value, base=10):
    """Logarithmic normalization for better score distribution."""
    if value < 0:
        return 0.0
    return math.log10(value + 1) / math.log10(base)


def age_factor(created_at, now=None):
    """
    Calculate age factor (0-1 range).
    Mature projects (2-8 years) get higher scores.
    """
    try:
        if now is None:
            now = datetime.now(timezone.utc)

        created_time = datetime.strptime(
            created_at, "%Y-%m-%dT%H:%M:%SZ"
        ).replace(tzinfo=timezone.utc)

        years = (now - created_time).days / 365.25

        # Peak score at 3-5 years, decrease for too old/new
        if years < 0.5:
            return 0.3  # Too new
        elif years < 2:
            return 0.6 + (years - 0.5) * 0.2  # Growing: 0.6-0.9
        elif years < 5:
            return 0.9 + (years - 2) * 0.033  # Peak: 0.9-1.0
        elif years < 8:
            return 1.0 - (years - 5) * 0.05  # Mature: 1.0-0.85
        else:
            return 0.7 - min((years - 8) * 0.03, 0.4)  # Declining: 0.7-0.3
    except (ValueError, TypeError):
        # Fallback for malformed or missing dates
        return 0.5


def activity_factor(pushed_at, created_at, now=None):
    """
    Calculate recent activity factor (0-1 range).
    Recent updates indicate active maintenance.
    """
    try:
        if now is None:
            now = datetime.now(timezone.utc)

        pushed_time = datetime.strptime(
            pushed_at, "%Y-%m-%dT%H:%M:%SZ"
        ).replace(tzinfo=timezone.utc)
        created_time = datetime.strptime(
            created_at, "%Y-%m-%dT%H:%M:%SZ"
        ).replace(tzinfo=timezone.utc)

        days_since_push = (now - pushed_time).days
        project_age_days = (now - created_time).days

        # Avoid division by zero / ultra-new repos
        if project_age_days < 1:
            return 1.0

        # Recent activity is good
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
            # Check if abandoned (no update in years)
            return max(0.2, 0.5 - (days_since_push - 365) / 3650)
    except (ValueError, TypeError):
        # Fallback for malformed or missing dates
        return 0.5


def health_factor(open_issues, stars):
    """
    Calculate project health (0-1 range).
    Issues relative to popularity.
    """
    if stars < 10:
        return 1.0 if open_issues < 5 else 0.8

    # Issue ratio relative to stars
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


def calculate_github_score(project, now=None):
    """
    Enhanced SSR Algorithm:

    Base Metrics (70%):
      - Stars: 40% (primary popularity indicator)
      - Forks: 20% (engagement and derivative work)
      - Watchers: 10% (ongoing interest)

    Quality Factors (30%):
      - Age: 10% (project maturity)
      - Activity: 10% (recent maintenance)
      - Health: 10% (issue management)

    Uses logarithmic scaling for better distribution.

    Returns:
        final_score (int): 0-10000 integer score.
        components (dict): individual component scores (0-1 range before scaling).
    """
    if now is None:
        now = datetime.now(timezone.utc)

    stars = project.get("stars", 0)
    forks = project.get("forks", 0)
    watchers = project.get("watchers", 0)
    open_issues = project.get("open_issues", 0)
    created_at = project.get("created_at", "2020-01-01T00:00:00Z")
    pushed_at = project.get("pushed_at", created_at)

    # Base metrics with logarithmic scaling
    stars_score = log_normalize(stars, base=100000) * 0.40
    forks_score = log_normalize(forks, base=10000) * 0.20
    watchers_score = log_normalize(watchers, base=10000) * 0.10

    # Quality factors
    age_score = age_factor(created_at, now=now) * 0.10
    activity_score = activity_factor(pushed_at, created_at, now=now) * 0.10
    health_score = health_factor(open_issues, stars) * 0.10

    # Total score (0-1 range)
    normalized_score = (
        stars_score
        + forks_score
        + watchers_score
        + age_score
        + activity_score
        + health_score
    )

    # Scale to 0-10000 for better readability
    final_score = int(normalized_score * 10000)

    components = {
        "stars": stars_score,
        "forks": forks_score,
        "watchers": watchers_score,
        "age": age_score,
        "activity": activity_score,
        "health": health_score,
    }

    return final_score, components


def classify_language(language):
    """Classify language into major categories."""
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


def format_project(project, score, components=None):
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
    if components is not None:
        data["score_breakdown"] = components
    return data


def main():
    import sys

    # Accept filename from command line or use default
    if len(sys.argv) > 1:
        data_file = sys.argv[1]
    else:
        # Find the latest projects file
        import glob

        files = glob.glob("data/seattle_projects_*.json")
        if not files:
            print("❌ No project data files found in data/")
            return
        data_file = max(files)  # Get the latest file

    print(f"📂 Loading data from {data_file}...")
    with open(data_file, "r") as f:
        data = json.load(f)

    projects = data.get("projects", [])
    print(f"📦 Loaded {len(projects):,} projects")

    # Use a single "now" timestamp for this run
    now_utc = datetime.now(timezone.utc)

    # Calculate scores and classify by language
    by_language = defaultdict(list)

    for project in projects:
        score, components = calculate_github_score(project, now=now_utc)
        language_category = classify_language(project.get("language"))
        formatted = format_project(project, score, components=components)
        by_language[language_category].append(formatted)

    # Sort each language by score
    for language in by_language:
        by_language[language].sort(key=lambda x: x["score"], reverse=True)

    # Create output directories
    pages_dir = "frontend/public/pages"
    os.makedirs(pages_dir, exist_ok=True)

    pages_build_dir = "frontend/build/pages"
    os.makedirs(pages_build_dir, exist_ok=True)

    # Generate metadata file (total counts per language)
    from zoneinfo import ZoneInfo

    SEATTLE_TZ = ZoneInfo("America/Los_Angeles")

    metadata = {
        "languages": {},
        "page_size": PAGE_SIZE,
        "last_updated": datetime.now(SEATTLE_TZ).strftime("%Y-%m-%d %H:%M:%S %Z"),
    }

    print(f"\n📊 Generating paginated data:")

    total_all = sum(len(p) for p in by_language.values()) or 1

    for language, lang_projects in sorted(
        by_language.items(), key=lambda x: len(x[1]), reverse=True
    ):
        total_projects = len(lang_projects)
        total_pages = (total_projects + PAGE_SIZE - 1) // PAGE_SIZE  # Ceiling division

        metadata["languages"][language] = {
            "total": total_projects,
            "pages": total_pages,
        }

        # Create directory for this language
        lang_dir = os.path.join(pages_dir, language.lower().replace("+", "plus"))
        os.makedirs(lang_dir, exist_ok=True)

        lang_build_dir = os.path.join(
            pages_build_dir, language.lower().replace("+", "plus")
        )
        os.makedirs(lang_build_dir, exist_ok=True)

        # Generate page files
        for page_num in range(total_pages):
            start_idx = page_num * PAGE_SIZE
            end_idx = min(start_idx + PAGE_SIZE, total_projects)
            page_data = lang_projects[start_idx:end_idx]

            page_file = os.path.join(lang_dir, f"page_{page_num + 1}.json")
            with open(page_file, "w") as f:
                json.dump(page_data, f, separators=(",", ":"))

            # Copy to build directory
            build_page_file = os.path.join(lang_build_dir, f"page_{page_num + 1}.json")
            with open(build_page_file, "w") as f:
                json.dump(page_data, f, separators=(",", ":"))

        percentage = total_projects / total_all * 100
        print(
            f"  ✅ {language}: {total_projects:,} projects ({percentage:.1f}%) → {total_pages} pages"
        )

    # Save metadata
    metadata_file = "frontend/public/metadata.json"
    with open(metadata_file, "w") as f:
        json.dump(metadata, f, indent=2)

    # Copy to build
    with open("frontend/build/metadata.json", "w") as f:
        json.dump(metadata, f, indent=2)

    print(f"\n✅ Saved metadata to {metadata_file}")
    print(
        f"\n🎉 Done! Generated {sum(m['pages'] for m in metadata['languages'].values())} page files"
    )
    print(f"   Each page contains up to {PAGE_SIZE} projects")
    print(
        f"   Total size: ~{sum(m['total'] for m in metadata['languages'].values()):,} projects"
    )


if __name__ == "__main__":
    main()