import random
import re
import pandas as pd
import requests
import streamlit as st


def extract_imdb_id(imdb_url: str) -> str | None:
    match = re.search(r"/title/(tt\d+)", str(imdb_url))
    return match.group(1) if match else None


def build_tmdb_poster_url(poster_path: str | None, size: str = "w500") -> str | None:
    if not poster_path:
        return None
    return f"https://image.tmdb.org/t/p/{size}{poster_path}"


@st.cache_data(show_spinner=False, ttl=86400)
def fetch_tmdb_poster(movie_title: str, imdb_url: str, year: int | None = None) -> str | None:
    """
    Tries to get the poster from TMDb.
    Priority:
    1. IMDb ID extracted from IMDb URL
    2. Title search fallback
    """
    if "TMDB_BEARER_TOKEN" not in st.secrets:
        raise KeyError("TMDB_BEARER_TOKEN was not found in st.secrets")

    tmdb_token = st.secrets["TMDB_BEARER_TOKEN"]

    headers = {
        "Authorization": f"Bearer {tmdb_token}",
        "accept": "application/json",
    }

    session = requests.Session()

    imdb_id = extract_imdb_id(imdb_url)
    if imdb_id:
        try:
            find_url = f"https://api.themoviedb.org/3/find/{imdb_id}"
            params = {"external_source": "imdb_id"}
            res = session.get(find_url, headers=headers, params=params, timeout=15)
            res.raise_for_status()
            data = res.json()

            movie_results = data.get("movie_results", [])
            if movie_results:
                poster_path = movie_results[0].get("poster_path")
                poster_url = build_tmdb_poster_url(poster_path)
                if poster_url:
                    print(f"Poster found via TMDb find endpoint for {movie_title}: {poster_url}")
                    return poster_url
        except Exception as e:
            print(f"TMDb find lookup failed for {movie_title}: {e}")

    try:
        search_url = "https://api.themoviedb.org/3/search/movie"
        params = {"query": movie_title}

        if year is not None:
            params["year"] = year

        res = session.get(search_url, headers=headers, params=params, timeout=15)
        res.raise_for_status()
        data = res.json()

        results = data.get("results", [])

        if not results:
            print(f"No TMDb search results for {movie_title}")
            return None

        exact_title_matches = [
            r for r in results
            if str(r.get("title", "")).strip().lower() == movie_title.strip().lower()
        ]
        if exact_title_matches:
            results = exact_title_matches

        if year is not None:
            year_matches = [
                r for r in results
                if str(r.get("release_date", "")).startswith(str(year))
            ]
            if year_matches:
                results = year_matches

        poster_path = results[0].get("poster_path")
        poster_url = build_tmdb_poster_url(poster_path)

        if poster_url:
            print(f"Poster found via TMDb title search for {movie_title}: {poster_url}")
            return poster_url

        print(f"TMDb found movie for {movie_title}, but no poster path was available.")
        return None

    except Exception as e:
        print(f"TMDb search failed for {movie_title}: {e}")
        return None


def get_movie_row(movie_title: str) -> pd.Series | None:
    df = st.session_state.df
    matches = df[df["Title"] == movie_title]

    if matches.empty:
        return None

    return matches.iloc[0]


def get_movie_poster(movie_title: str) -> str | None:
    movie_row = get_movie_row(movie_title)

    if movie_row is None:
        print(f"Movie not found in dataframe: {movie_title}")
        return None

    imdb_url = movie_row.get("URL", "")
    year = None

    if "Year" in movie_row.index and pd.notna(movie_row["Year"]):
        try:
            year = int(movie_row["Year"])
        except Exception:
            year = None

    print(f"Searching poster for: {movie_title}")
    print(f"IMDb URL: {imdb_url}")
    print(f"Year: {year}")

    return fetch_tmdb_poster(movie_title, imdb_url, year)


def get_movie_imdb_url(movie_title: str) -> str | None:
    movie_row = get_movie_row(movie_title)
    if movie_row is None:
        return None
    return movie_row.get("URL", None)


def initialize_watchlist(uploaded_file):
    uploaded_file.seek(0)
    df = pd.read_csv(uploaded_file)

    movies_df = df[df["Title Type"].astype(str).str.lower() == "movie"].copy()
    movies_df = movies_df.dropna(subset=["Title", "URL"])

    st.session_state.df = movies_df
    st.session_state.watchlist = movies_df["Title"].tolist()
    st.session_state.pick_count = 0

    if len(st.session_state.watchlist) >= 2:
        st.session_state.current_pair = random.sample(st.session_state.watchlist, 2)
    else:
        st.session_state.current_pair = []


def reset_app_state():
    for key in ["df", "watchlist", "current_pair", "uploaded_signature", "pick_count"]:
        st.session_state.pop(key, None)


def get_turn_circle() -> str:
    pick_count = st.session_state.get("pick_count", 0)
    return "🔵" if pick_count % 2 == 0 else "🔴"


def render_movie_card(movie_title: str, button_key: str, loser_title: str):
    poster = get_movie_poster(movie_title)
    imdb_url = get_movie_imdb_url(movie_title)

    if poster:
        st.image(poster, width=250)
    else:
        st.info("Poster not found")

    if imdb_url:
        st.markdown(f"[link]({imdb_url})")

    if st.button(movie_title, key=button_key, use_container_width=True):
        st.session_state.watchlist.remove(loser_title)
        st.session_state.pick_count = st.session_state.get("pick_count", 0) + 1

        if len(st.session_state.watchlist) > 1:
            st.session_state.current_pair = random.sample(st.session_state.watchlist, 2)

        st.rerun()


# App UI
st.title("🏆 Movie Tournament Picker")
st.write("https://www.imdb.com/user/ur56681304/watchlist/")

uploaded_file = st.file_uploader("Upload your watchlist.csv", type="csv")

if uploaded_file:
    if "TMDB_BEARER_TOKEN" not in st.secrets:
        st.error("Add TMDB_BEARER_TOKEN to .streamlit/secrets.toml before running the app.")
        st.stop()

    uploaded_signature = f"{uploaded_file.name}-{uploaded_file.size}"

    if (
        "watchlist" not in st.session_state
        or st.session_state.get("uploaded_signature") != uploaded_signature
    ):
        st.session_state.uploaded_signature = uploaded_signature
        initialize_watchlist(uploaded_file)

    watchlist = st.session_state.watchlist

    if len(watchlist) > 1:
        picks_remaining = len(watchlist) - 1
        circle = get_turn_circle()

        st.write(f"### {picks_remaining} picks remaining. Pick your favorite! {circle}")

        col1, col2 = st.columns(2)
        m1, m2 = st.session_state.current_pair

        with col1:
            _, center1, _ = st.columns([1, 3, 1])
            with center1:
                render_movie_card(m1, f"left_{m1}", m2)

        with col2:
            _, center2, _ = st.columns([1, 3, 1])
            with center2:
                render_movie_card(m2, f"right_{m2}", m1)

    elif len(watchlist) == 1:
        winner = watchlist[0]
        winner_poster = get_movie_poster(winner)
        winner_imdb_url = get_movie_imdb_url(winner)

        st.balloons()
        st.success(f"## The winner is {winner}!")

        _, center, _ = st.columns([1, 2, 1])
        with center:
            if winner_poster:
                st.image(winner_poster, width=300)
            else:
                st.info("Poster not found")

            if winner_imdb_url:
                st.markdown(f"[link]({winner_imdb_url})")

        if st.button("Start Over", use_container_width=True):
            reset_app_state()
            st.rerun()

    else:
        st.warning("No movies were found in the uploaded CSV.")