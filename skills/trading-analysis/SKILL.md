---
name: "trading-analysis"
description: "Analyze trading opportunities and provide insights. Use when user asks about trading, markets, or financial analysis."
version: "1.0.0"
author: "Binary Rogue"
tags: ["trading", "finance", "analysis"]
trigger_patterns:
  - "trading"
  - "market analysis"
  - "trade"
  - "forex"
  - "stocks"
allowed_tools:
  - "code_execution"
  - "memory"
---

# Trading Analysis Skill

## When to Use
Activate when user asks about:
- Trading opportunities
- Market analysis
- Price movements
- Trade recommendations
- Financial insights

## Analysis Process

### Step 1: Gather Data
- Check current market prices
- Review recent price history
- Identify key support/resistance levels

### Step 2: Technical Analysis
- Analyze moving averages (EMA 20, EMA 50)
- Check RSI for overbought/oversold conditions
- Look for chart patterns

### Step 3: Risk Assessment
- Evaluate position size
- Check stop-loss levels
- Assess risk/reward ratio

### Step 4: Recommendation
Provide clear:
- Entry point
- Stop loss
- Take profit
- Rationale

## Example Output

**Analysis for EUR/USD:**
- Current: 1.1850
- EMA20: 1.1845 (trend: bullish)
- RSI: 45 (neutral)
- Recommendation: BUY with SL 1.1820, TP 1.1910
