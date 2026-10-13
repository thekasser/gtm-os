"""Offline checks for the preparation facts supplied to Account Brain.

Run from the repo root: python -m unittest discover -s prototype/tests -v
These check prompt context and preparation, not live-model compliance.
"""
import json
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agt902 import (
    SYSTEM_PROMPT, build_user_prompt, _summarize_usage,
    _summarize_health, _summarize_payments,
)
from validation import validate_all


def usage_rows(count):
    # Every other day: records must not be described as calendar-day coverage.
    return [dict(period_start=(date(2026, 1, 1) + timedelta(days=2*i)).isoformat(),
                 units_consumed=10, overage_units=2, overage_amount_usd=1)
            for i in range(count)]


class AccountMethodologyTests(unittest.TestCase):
    def prompt_view(self, components):
        view = dict(account_id='synthetic-example', components=components,
                    view_metadata=dict(is_stale=True,
                                       last_refresh_timestamp='2026-01-01T00:00:00Z'))
        prompt = build_user_prompt(view, 'What should the account team do?')
        # Adding explanatory context must not alter the actual model inputs.
        supplied = json.loads(prompt.split('```json\n', 1)[1].split('\n```', 1)[0])
        self.assertEqual(supplied, view)
        self.assertIn('Account view preparation:', prompt)
        return supplied

    def test_answer_instructions_require_numbered_methodology(self):
        self.assertIn('How this was pulled:', SYSTEM_PROMPT)
        self.assertIn('numbered list', SYSTEM_PROMPT)

    def test_preparation_guidance_describes_record_based_windows(self):
        prompt = ' '.join(build_user_prompt({}, 'Summarize usage.').split())
        self.assertIn('select the last 30/90 supplied records (or all available if fewer)', prompt)
        self.assertIn('not calendar-date filters. n_days is a record count.', prompt)

    def test_preparation_guidance_discloses_unavailable_details(self):
        prompt = ' '.join(build_user_prompt({}, 'Summarize usage.').split())
        self.assertIn('Exact trailing-window dates are not captured in this view.', prompt)
        self.assertIn('Source/access details not supplied elsewhere are not captured.', prompt)
        self.assertIn('Do not turn an unavailable count or date into zero or a guess.', prompt)

    def test_answer_instructions_prohibit_invented_methodology(self):
        prompt = ' '.join(SYSTEM_PROMPT.split())
        self.assertIn('Do not invent SQL/SOQL, connectors, permissions, filters, exclusions, '
                      'record counts, or exact date ranges.', prompt)
        self.assertIn('Say "not captured" when a relevant detail is unavailable.', prompt)

    def test_full_usage_history_counts_records_not_calendar_days(self):
        usage = _summarize_usage(usage_rows(95))
        supplied = self.prompt_view(dict(usage_metering=usage))
        self.assertEqual(supplied['components']['usage_metering']['trailing_30d'],
                         dict(n_days=30, total_units_consumed=300,
                              mean_daily_units=10, total_overage_units=60,
                              days_with_overage=30))
        self.assertEqual(usage['trailing_90d']['n_days'], 90)
        self.assertEqual(usage['trailing_90d']['total_units_consumed'], 900)

    def test_short_history_uses_available_records(self):
        usage = _summarize_usage(usage_rows(3))
        self.prompt_view(dict(usage_metering=usage))
        self.assertEqual(usage['trailing_30d']['n_days'], 3)
        self.assertEqual(usage['trailing_90d']['total_units_consumed'], 30)

    def test_empty_and_unavailable_data_remain_distinct(self):
        supplied = self.prompt_view(dict(usage_metering=_summarize_usage([]),
                                        conversation_intel=[], qbr_history='not_in_corpus'))
        self.assertIsNone(supplied['components']['usage_metering']['trailing_30d'])
        self.assertEqual(supplied['components']['conversation_intel'], [])
        self.assertEqual(supplied['components']['qbr_history'], 'not_in_corpus')

    def test_health_lookback_preserves_observed_date(self):
        rows = [dict(observation_date=(date(2026, 1, 1) + timedelta(days=2*i)).isoformat(),
                     score=50+i, tier='healthy', payment_health_status='current')
                for i in range(31)]
        health = _summarize_health(rows)
        self.prompt_view(dict(customer_health=health))
        self.assertEqual(health['snapshots']['30_days_ago']['date'], '2026-01-01')
        self.assertEqual(health['current']['date'], '2026-03-02')
        self.assertEqual(health['trajectory_30d'], 'improving')

    def test_payment_transition_count_includes_events_outside_recent_ten(self):
        rows = [dict(event_type='test', new_state='current', prior_state='failed' if i < 2 else 'current',
                     event_at=f'2026-01-{i+1:02d}', transition_reason='Synthetic example')
                for i in range(12)]
        payments = _summarize_payments(rows)
        self.prompt_view(dict(payment_health=payments))
        self.assertEqual(len(payments['recent_events']), 10)
        self.assertEqual(payments['recent_events'][0]['event_at'], '2026-01-03')
        self.assertEqual(payments['transitions_count'], 2)

    def test_offline_example_matches_prepared_data_and_resolves_citations(self):
        fixture = json.loads((Path(__file__).parent / 'fixtures' /
                              'account_methodology_example.json').read_text())
        view = fixture['preparation_view']
        self.assertEqual(view['components']['usage_metering'],
                         _summarize_usage(usage_rows(3)))
        self.prompt_view(view['components'])
        row = fixture['samples'][0]['brain_row']
        self.assertEqual(validate_all(row).issues, [])
        self.assertEqual(row['tool_calls_made'], [])
        self.assertEqual(row['account_id'], view['account_id'])


if __name__ == '__main__':
    unittest.main()
