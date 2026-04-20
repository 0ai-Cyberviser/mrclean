# MrClean v0.4.1 Enhancements

## Zero-Day Detection

MrClean now includes enhanced zero-day vulnerability detection in its assessment system. The system automatically identifies potential security vulnerabilities and critical failures:

### Security Check Detection

The assessment engine monitors for failures in security-focused checks:
- **Static Analysis**: `semgrep`, `codeql`, `snyk`, `dependabot`
- **Dependency Scanning**: `socket`, `security`, `vulnerability`
- **Custom Security Gates**: Any check containing security-related keywords

When security checks fail, the system:
- Flags findings as `critical` severity
- Marks assessment outcome as requiring verification
- Reduces confidence scores appropriately
- Provides targeted recommendations for investigation

### Fuzzing Failure Detection

Fuzzing failures often reveal memory corruption, crashes, and other critical bugs:
- **Supported Fuzzers**: `oss-fuzz`, `cifuzz`, `libfuzzer`, `afl`, `fuzzing`
- **Detection**: Automatically identifies fuzzing check failures
- **Severity**: Marks as `critical` severity
- **Context**: Flags potential memory corruption issues

### Multi-Security Failure Analysis

When multiple security checks fail simultaneously:
- Detects complex vulnerability patterns
- Flags as `high` severity
- Increases runtime risk scores
- Recommends comprehensive security review

### Assessment Codes

New assessment finding codes:
- `security_check_failure`: Security-focused checks failing
- `fuzzing_failure`: Fuzzing checks detecting crashes/corruption
- `multi_security_failure`: Multiple security checks failing together

### Example

```python
# PR with security failures gets flagged
result = ScanResult(
    failing_checks=("semgrep", "codeql", "oss-fuzz"),
    # ... other fields
)

report = CandidateAssessor().assess((result,), (candidate,))[0]

# report.findings will include:
# - security_check_failure (critical)
# - fuzzing_failure (critical)
# - multi_security_failure (high)
```

## Multi-Model Routing

MrClean now supports intelligent routing to different AI models based on task type and complexity.

### Configuration

Add multiple models with task-specific routing:

```toml
[model]
provider = "openai"
name = "gpt-5.4-mini"  # Default fallback model

# High-capacity model for security-critical tasks
[[models]]
provider = "openai"
name = "gpt-5.4-turbo"
task_types = ["security", "vulnerability", "zero-day"]
priority = 100

# Efficient model for routine tasks
[[models]]
provider = "openai"
name = "gpt-5.4-mini"
task_types = ["planning", "proposal", "review"]
priority = 50
```

### Model Selection Logic

The routing system selects models using this algorithm:
1. Filter models matching the requested task type
2. Among matches, select the highest priority model
3. Fall back to default model if no matches

### Task Types

Configure models for specific task types:
- `security`: Security analysis and vulnerability assessment
- `vulnerability`: Vulnerability detection and remediation
- `zero-day`: Zero-day vulnerability investigation
- `planning`: Cleanup plan generation
- `proposal`: Edit proposal generation
- `review`: Code review and analysis

### Priority System

- Higher priority numbers = preferred selection
- Allows upgrading to more capable models for critical tasks
- Cost optimization by routing routine tasks to efficient models

### API

```python
# Get the best model for a task type
config = MrCleanConfig.from_toml("mrclean.toml")
security_model = config.get_model_for_task("security")
planning_model = config.get_model_for_task("planning")

# Agent automatically selects appropriate model
agent.draft_plan(signal, task_type="security")

# Proposal generator uses task-specific routing
generator.generate(candidate, session, task_type="vulnerability")
```

### Benefits

1. **Cost Optimization**: Route simple tasks to efficient models
2. **Quality Improvement**: Use powerful models for critical security work
3. **Flexibility**: Easy model experimentation and A/B testing
4. **Scalability**: Adapt to new models without code changes

### Backward Compatibility

- Single-model configurations continue to work
- Default model is used when no task-specific routing is configured
- Empty `models` array falls back to default model
- Optional `task_types` and `priority` fields

## Testing

Comprehensive test coverage added:
- `test_assess_detects_security_check_failures_as_zero_day_indicators`
- `test_assess_detects_fuzzing_failures_as_zero_day_indicators`
- `test_multi_model_routing_selects_best_match`

Run tests:
```bash
python -m pytest tests/test_assess.py tests/test_config.py -v
```

## Migration Guide

### From v0.4.0 to v0.4.1

No breaking changes. Existing configurations work without modification.

To enable multi-model routing:
1. Add `[[models]]` sections to your TOML config
2. Specify `task_types` and `priority` for each model
3. Models are automatically selected based on task context

To leverage zero-day detection:
1. No configuration changes needed
2. Security and fuzzing check failures are automatically detected
3. Review assessment findings for new security-related codes
4. Adjust workflows based on `critical` severity findings

## Architecture

### Zero-Day Detection Architecture

```
monitor.py → assess.py → _check_zero_day_indicators()
                ↓
           AssessmentFinding(code="security_check_failure"|"fuzzing_failure")
                ↓
           runtime_score += 3, confidence -= 30
```

### Multi-Model Routing Architecture

```
config.py → get_model_for_task(task_type)
    ↓
MrCleanAgent.draft_plan(task_type="planning")
    ↓
ProposalGenerator.generate(task_type="proposal")
    ↓
model_client.complete(model=selected_model.name)
```

## Future Enhancements

Potential future improvements:
- Machine learning-based vulnerability classification
- Historical pattern analysis for zero-day detection
- Dynamic model selection based on repository context
- Integration with external threat intelligence feeds
- Custom task type definitions per repository
- Model performance tracking and automatic optimization
