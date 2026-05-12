"""
DSPy Signatures for rubric evaluation.

Convention:
  - All rubric signatures return `passed: bool` and `reason: str`
  - Use dspy.Predict (not ChainOfThought) for rubric evals — we want fast,
    structured pass/fail decisions, not reasoning chains
  - All rubric evals run on HAIKU_MODEL from config
  - Field descriptions are the single source of truth for what good looks like
"""
import dspy


class JTBDCompletenessRubric(dspy.Signature):  # type: ignore[misc]
    """
    Evaluate if a job-to-be-done statement describes a functional outcome
    that a person actively pursues, not just a state they are in.

    POOR (fail): 'They need project management', 'They want to be efficient',
                 'They are developers who use tools'
    GOOD (pass): 'Track engineering work without switching context mid-flow',
                 'Get SOC 2 compliant before their first enterprise deal closes',
                 'Ship features faster without blocking code review on their team'

    The JTBD should answer: what does this person actually DO or ACHIEVE?
    """

    segment_name: str = dspy.InputField(desc="The customer segment this JTBD belongs to")
    jtbd: str = dspy.InputField(desc="The job-to-be-done statement to evaluate")
    passed: bool = dspy.OutputField(
        desc="True if JTBD describes a specific functional outcome someone pursues"
    )
    reason: str = dspy.OutputField(
        desc="One sentence: why it passes, or what specific change would make it pass"
    )


class SegmentNamingRubric(dspy.Signature):  # type: ignore[misc]
    """
    Evaluate if a customer segment name is specific enough to uniquely identify
    a persona — someone who could tell from the name alone whether it describes them.

    POOR (fail): 'Business users', 'Enterprise customers', 'Teams',
                 'General audience', 'Product users', 'Small businesses'
    GOOD (pass): 'Efficiency-focused solo developers',
                 'Enterprise compliance buyers at pre-IPO SaaS',
                 'Growth-stage PM teams shipping without engineering bottlenecks'
    """

    segment_name: str = dspy.InputField(desc="The segment name to evaluate")
    passed: bool = dspy.OutputField(
        desc="True if someone reading this name could tell if it describes them"
    )
    reason: str = dspy.OutputField(
        desc="One sentence: what makes it specific enough, or what specificity is missing"
    )


class ReactionCoherenceRubric(dspy.Signature):  # type: ignore[misc]
    """
    Evaluate if a reaction's reasoning explicitly traces from the segment's
    job-to-be-done and churn triggers to the predicted outcome.

    A coherent reaction does NOT say 'customers may be price-sensitive'.
    It says 'this segment's JTBD is X; the decision threatens Y which is their
    primary churn trigger; therefore the predicted churn range is Z'.

    Check for: (1) JTBD is referenced or clearly implied, (2) at least one
    churn trigger is named specifically.
    """

    segment_jtbd: str = dspy.InputField(desc="The segment's job-to-be-done")
    segment_churn_triggers: str = dspy.InputField(
        desc="The segment's named churn triggers, comma-separated"
    )
    reasoning_trace: str = dspy.InputField(
        desc="The reaction agent's reasoning trace to evaluate"
    )
    passed: bool = dspy.OutputField(
        desc="True if reasoning explicitly traces JTBD and at least one churn trigger to outcome"
    )
    reason: str = dspy.OutputField(
        desc="One sentence: what the reasoning correctly traces, or what is missing"
    )


class SpecificityRubric(dspy.Signature):  # type: ignore[misc]
    """
    Evaluate if a top_concern names a specific product feature, workflow element,
    or observable customer behavior — not a generic market observation.

    POOR (fail): 'pricing too high', 'competition is a factor',
                 'customers might not adopt', 'users may churn'
    GOOD (pass): 'keyboard-first workflow dependency on slash commands',
                 'CSV export for quarterly board reporting workflow',
                 'Slack integration used for async standups by 80% of this segment'
    """

    top_concern: str = dspy.InputField(
        desc="The reaction agent's stated top concern for this segment-option pair"
    )
    product_name: str = dspy.InputField(desc="The product being simulated")
    passed: bool = dspy.OutputField(
        desc="True if top_concern names a specific feature or workflow, not a generic observation"
    )
    reason: str = dspy.OutputField(
        desc="One sentence explanation of why it is or isn't specific"
    )


class DASubstantivenessRubric(dspy.Signature):  # type: ignore[misc]
    """
    Evaluate if a devil's advocate counter-case is:
    (1) Specific to this segment and decision option — not generic market skepticism
    (2) Falsifiable — proposes a concrete test that would prove or disprove it

    POOR (fail): 'Some customers might not like the price increase',
                 'There could be competitive risk', 'Market conditions may change'
    GOOD (pass): 'If this segment's usage of [feature X] drops more than 20%
                  in the first 30 days post-pricing, the 12-18% churn estimate
                  is wrong — their JTBD depends on that feature being zero-friction'
    """

    segment_name: str = dspy.InputField()
    decision_option: str = dspy.InputField(desc="The option being challenged")
    original_reaction: str = dspy.InputField(desc="The reaction being counter-argued")
    counter_case: str = dspy.InputField(desc="The devil's advocate case to evaluate")
    substantive: bool = dspy.OutputField(
        desc="True if counter-case is specific to this segment and option, not generic"
    )
    falsifiable: bool = dspy.OutputField(
        desc="True if counter-case includes a concrete condition that would disprove the reaction"
    )
    passed: bool = dspy.OutputField(
        desc="True if both substantive AND falsifiable — both required"
    )
    reason: str = dspy.OutputField(
        desc="One sentence on what makes it pass/fail, naming the specific gap if failing"
    )
