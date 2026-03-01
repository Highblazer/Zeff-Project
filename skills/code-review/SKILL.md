---
name: "code-review"
description: "Review code for quality, security, and best practices. Use when user asks to review, check, or analyze code."
version: "1.0.0"
author: "Binary Rogue"
tags: ["code", "review", "quality"]
trigger_patterns:
  - "review code"
  - "check code"
  - "refactor"
  - "code quality"
allowed_tools:
  - "code_execution"
---

# Code Review Skill

## When to Use
Activate when user asks to review, check, or analyze code.

## Review Checklist

### Security
- [ ] Input validation present
- [ ] No hardcoded secrets
- [ ] SQL injection prevention
- [ ] XSS protection

### Error Handling
- [ ] Try-catch blocks where needed
- [ ] Proper error messages
- [ ] Logging in place

### Performance
- [ ] No unnecessary loops
- [ ] Efficient data structures
- [ ] Database queries optimized

### Code Quality
- [ ] Clear variable names
- [ ] Functions are focused
- [ ] Comments explain why, not what
- [ ] Tests included

## Output Format

```
## Code Review: [filename]

### Issues Found
1. [Severity] Description

### Recommendations
- Suggestion 1
- Suggestion 2

### Score: X/10
```
