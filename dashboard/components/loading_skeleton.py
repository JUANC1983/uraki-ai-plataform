# dashboard/components/loading_skeleton.py
"""
Loading skeletons — placeholder UI shown while data is being fetched.
Prevents blank white flashes and communicates that the system is working.
"""
import streamlit as st
from styles.theme import COLORS


def case_list_skeleton(count: int = 5) -> None:
    """Skeleton for the case queue column."""
    c = COLORS
    for _ in range(count):
        st.markdown(f"""
        <div style="
            padding:0.75rem 1rem;
            border-bottom:1px solid {c['border_subtle']};
            animation:skeleton-pulse 1.5s ease-in-out infinite;
        ">
            <div style="display:flex;justify-content:space-between;margin-bottom:6px;">
                <div class="skel" style="width:80px;height:10px;border-radius:4px;"></div>
                <div class="skel" style="width:50px;height:10px;border-radius:4px;"></div>
            </div>
            <div class="skel" style="width:70%;height:13px;border-radius:4px;margin-bottom:5px;"></div>
            <div class="skel" style="width:50%;height:11px;border-radius:4px;margin-bottom:8px;"></div>
            <div style="display:flex;justify-content:space-between;">
                <div class="skel" style="width:60px;height:10px;border-radius:4px;"></div>
                <div class="skel" style="width:40px;height:3px;border-radius:3px;margin-top:4px;"></div>
            </div>
        </div>
        <style>
        .skel {{
            background: linear-gradient(
                90deg,
                {c['bg_elevated']} 25%,
                {c['bg_secondary']} 50%,
                {c['bg_elevated']} 75%
            );
            background-size: 200% 100%;
            animation: skeleton-shimmer 1.5s infinite;
        }}
        @keyframes skeleton-shimmer {{
            0%   {{ background-position: 200% 0; }}
            100% {{ background-position: -200% 0; }}
        }}
        </style>
        """, unsafe_allow_html=True)


def decision_card_skeleton() -> None:
    """Skeleton for the decision card center panel."""
    c = COLORS
    st.markdown(f"""
    <div style="padding:1rem 0;animation:skeleton-pulse 1.5s ease-in-out infinite;">
        <!-- Header -->
        <div style="display:flex;justify-content:space-between;margin-bottom:0.75rem;
            padding-bottom:0.75rem;border-bottom:1px solid {c['border_subtle']};">
            <div style="display:flex;gap:8px;">
                <div class="skel" style="width:100px;height:14px;border-radius:4px;"></div>
                <div class="skel" style="width:80px;height:14px;border-radius:4px;"></div>
            </div>
            <div class="skel" style="width:70px;height:14px;border-radius:4px;"></div>
        </div>

        <!-- Action block -->
        <div style="background:{c['bg_elevated']};border:1px solid {c['border_subtle']};
            border-radius:12px;padding:1.1rem;margin-bottom:0.75rem;">
            <div class="skel" style="width:120px;height:10px;border-radius:4px;margin-bottom:8px;"></div>
            <div style="display:flex;gap:12px;align-items:center;">
                <div class="skel" style="width:36px;height:36px;border-radius:8px;"></div>
                <div>
                    <div class="skel" style="width:220px;height:18px;border-radius:4px;margin-bottom:6px;"></div>
                    <div class="skel" style="width:100px;height:11px;border-radius:4px;"></div>
                </div>
            </div>
        </div>

        <!-- Client block -->
        <div style="background:{c['bg_elevated']};border:1px solid {c['border_subtle']};
            border-radius:10px;padding:0.9rem;margin-bottom:0.75rem;">
            <div class="skel" style="width:80px;height:10px;border-radius:4px;margin-bottom:8px;"></div>
            <div class="skel" style="width:55%;height:16px;border-radius:4px;margin-bottom:6px;"></div>
            <div class="skel" style="width:70%;height:12px;border-radius:4px;margin-bottom:10px;"></div>
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;">
                <div class="skel" style="height:52px;border-radius:8px;"></div>
                <div class="skel" style="height:52px;border-radius:8px;"></div>
                <div class="skel" style="height:52px;border-radius:8px;"></div>
                <div class="skel" style="height:52px;border-radius:8px;"></div>
            </div>
        </div>

        <!-- Reasoning -->
        <div style="margin-bottom:0.75rem;">
            <div class="skel" style="width:100%;height:44px;border-radius:6px;margin-bottom:6px;"></div>
            <div class="skel" style="width:100%;height:44px;border-radius:6px;"></div>
        </div>
    </div>

    <style>
    .skel {{
        background: linear-gradient(
            90deg,
            {c['bg_elevated']} 25%,
            {c['bg_secondary']} 50%,
            {c['bg_elevated']} 75%
        );
        background-size: 200% 100%;
        animation: skeleton-shimmer 1.5s infinite;
    }}
    @keyframes skeleton-shimmer {{
        0%   {{ background-position: 200% 0; }}
        100% {{ background-position: -200% 0; }}
    }}
    </style>
    """, unsafe_allow_html=True)


def metrics_skeleton() -> None:
    """Skeleton for the top metrics bar."""
    c = COLORS
    st.markdown(f"""
    <div style="display:flex;gap:1.5rem;padding:0.6rem 1.5rem;
        background:{c['bg_secondary']};border-bottom:1px solid {c['border_subtle']};">
        {''.join([f'''
        <div style="display:flex;align-items:center;gap:10px;">
            <div class="skel" style="width:36px;height:36px;border-radius:8px;"></div>
            <div>
                <div class="skel" style="width:30px;height:22px;border-radius:4px;margin-bottom:4px;"></div>
                <div class="skel" style="width:70px;height:10px;border-radius:4px;"></div>
            </div>
        </div>''' for _ in range(5)])}
    </div>
    <style>
    .skel {{
        background: linear-gradient(
            90deg,
            {c['bg_elevated']} 25%,
            {c['bg_secondary']} 50%,
            {c['bg_elevated']} 75%
        );
        background-size: 200% 100%;
        animation: skeleton-shimmer 1.5s infinite;
    }}
    @keyframes skeleton-shimmer {{
        0%   {{ background-position: 200% 0; }}
        100% {{ background-position: -200% 0; }}
    }}
    </style>
    """, unsafe_allow_html=True)


def inline_spinner(message: str = "Cargando...") -> None:
    """Compact inline loading indicator."""
    c = COLORS
    st.markdown(f"""
    <div style="
        display:flex;align-items:center;gap:10px;
        padding:0.75rem 1rem;
        background:{c['bg_elevated']};
        border:1px solid {c['border_subtle']};
        border-radius:8px;
        margin:0.5rem 0;
    ">
        <div style="
            width:14px;height:14px;border-radius:50%;
            border:2px solid {c['border_default']};
            border-top-color:{c['accent']};
            animation:spin 0.8s linear infinite;
        "></div>
        <span style="font-size:12px;color:{c['text_secondary']};">{message}</span>
    </div>
    <style>
    @keyframes spin {{ to {{ transform: rotate(360deg); }} }}
    </style>
    """, unsafe_allow_html=True)
