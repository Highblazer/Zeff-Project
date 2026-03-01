#!/usr/bin/env python3
"""
Browser Automation with OpenClaw + MiniMax-M2.5
A Streamlit interface for AI-powered browser automation
"""

import streamlit as st
import json
import time
from datetime import datetime

# Page config
st.set_page_config(
    page_title="OpenClaw Browser Automation",
    page_icon="🌐",
    layout="wide"
)

# Initialize session state
if "messages" not in st.session_state:
    st.session_state.messages = []

if "browser_url" not in st.session_state:
    st.session_state.browser_url = "https://news.ycombinator.com"

if "last_screenshot" not in st.session_state:
    st.session_state.last_screenshot = None

# Custom CSS
st.markdown("""
<style>
    .stApp {
        background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
    }
    .chat-message {
        padding: 1rem;
        border-radius: 0.5rem;
        margin-bottom: 1rem;
    }
    .user-msg {
        background: #0d47a1;
        color: white;
    }
    .ai-msg {
        background: #2e7d32;
        color: white;
    }
</style>
""", unsafe_allow_html=True)

# Title
st.title("🌐 OpenClaw Browser Automation")
st.markdown("**Powered by MiniMax-M2.5 + OpenClaw Browser Tool**")

# Sidebar
with st.sidebar:
    st.header("⚙️ Settings")
    
    model = st.selectbox(
        "Model",
        ["MiniMax-M2.5", "MiniMax-M2.1"],
        index=0
    )
    
    st.divider()
    
    st.header("🌍 Browser")
    
    url_input = st.text_input("URL", value=st.session_state.browser_url)
    
    if st.button("🚀 Navigate"):
        st.session_state.browser_url = url_input
        st.rerun()
    
    st.divider()
    
    # Quick actions
    st.header("⚡ Quick Actions")
    
    col1, col2 = st.columns(2)
    with col1:
        if st.button("📰 Hacker News"):
            st.session_state.browser_url = "https://news.ycombinator.com"
            st.rerun()
    with col2:
        if st.button("🔍 Google"):
            st.session_state.browser_url = "https://www.google.com"
            st.rerun()
    
    if st.button("📸 Take Screenshot"):
        st.info("Screenshot would be taken here")
    
    if st.button("🗑️ Clear Chat"):
        st.session_state.messages = []
        st.rerun()

# Main content
col_main, col_browser = st.columns([1, 2])

with col_main:
    st.header("💬 Chat")
    
    # Display messages
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
    
    # Chat input
    if prompt := st.chat_input("What would you like me to do?"):
        # Add user message
        st.session_state.messages.append({"role": "user", "content": prompt})
        
        # Display user message
        with st.chat_message("user"):
            st.markdown(prompt)
        
        # Show thinking
        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                # Process the request
                # This would use OpenClaw's browser tool
                response = f"🎯 Task: {prompt}\n\n"
                response += "**Executing browser action via OpenClaw...**\n\n"
                
                # Simulated response for demo
                if "navigate" in prompt.lower() or "go to" in prompt.lower() or "visit" in prompt.lower():
                    response += "✅ Browser navigation initiated\n"
                    response += f"🌐 Loading: {st.session_state.browser_url}\n"
                elif "search" in prompt.lower():
                    response += "🔍 Search initiated\n"
                    response += f"📍 Searching for relevant content...\n"
                elif "click" in prompt.lower():
                    response += "👆 Click action would be executed\n"
                elif "read" in prompt.lower() or "tell me" in prompt.lower():
                    response += "📖 Reading page content...\n"
                    response += "⚠️ Note: This is a demo interface. Full browser automation requires OpenClaw backend connection.\n"
                else:
                    response += "🤔 Processing your request...\n"
                
                response += f"\n**Model:** {model}\n"
                response += f"**Time:** {datetime.now().strftime('%H:%M:%S')}"
                
                st.markdown(response)
        
        # Add AI response
        st.session_state.messages.append({"role": "assistant", "content": response})

with col_browser:
    st.header("🖥️ Browser Preview")
    
    # Browser frame placeholder
    st.markdown("""
    <div style="
        background: #1e1e1e;
        border-radius: 10px;
        padding: 20px;
        min-height: 400px;
        display: flex;
        align-items: center;
        justify-content: center;
        flex-direction: column;
    ">
        <h2 style="color: #666;">🌐 Browser Window</h2>
        <p style="color: #888;">Connect to OpenClaw to enable browser automation</p>
        <p style="color: #555; font-size: 12px;">URL: {}</p>
    </div>
    """.format(st.session_state.browser_url), unsafe_allow_html=True)
    
    # Info
    st.info("💡 **Tip:** Tell me to navigate to a website, search for something, or read page content!")

# Status bar
st.divider()
col_status1, col_status2, col_status3 = st.columns(3)
with col_status1:
    st.metric("Model", model)
with col_status2:
    st.metric("Messages", len(st.session_state.messages))
with col_status3:
    st.metric("Status", "🟢 Active")
