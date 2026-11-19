"""Annual-premium endowment assurance valuation."""
from pathlib import Path
import argparse

import matplotlib.pyplot as plt
import pandas as pd

ROOT = Path(__file__).resolve().parent
DEFAULT_INPUT = ROOT / 'input' / 'life_insurance_input.xlsx'
DEFAULT_OUTPUT = ROOT / 'output'


def factors(age, term, interest, q_by_age, mortality_multiplier=1.0):
    """Annuity-due and endowment assurance EPVs for 1 unit of annual payment."""
    survival = 1.0
    annuity = 0.0
    endowment = 0.0
    for year in range(term):
        q = min(q_by_age[age + year] * mortality_multiplier, 0.999)
        annuity += survival / (1 + interest) ** year
        endowment += survival * q / (1 + interest) ** (year + 1)
        survival *= 1 - q
    # Include the maturity benefit for surviving policies.
    endowment += survival / (1 + interest) ** term
    return annuity, endowment


def gross_premium(sum_assured, age, term, assumptions, q_by_age):
    """Solve EPV(premiums) = EPV(benefits + initial + renewal expenses)."""
    a, A = factors(age, term, assumptions['pricing_interest'], q_by_age)
    fixed_initial = assumptions['initial_fixed_expense']
    first_pct = assumptions['initial_premium_pct']
    fixed_renewal = assumptions['renewal_fixed_expense']
    renewal_pct = assumptions['renewal_premium_pct']

    denominator = a - first_pct - renewal_pct * (a - 1)
    if denominator <= 0:
        raise ValueError('Invalid expenses: non-positive premium denominator')
    premium = (sum_assured * A + fixed_initial + fixed_renewal * (a - 1)) / denominator
    return premium, a, A


def prospective_reserve(t, age, term, sum_assured, premium, assumptions,
                        q_by_age, stressed=False):
    """Reserve just BEFORE the premium/expense due at policy anniversary t."""
    if t == term:
        return 0.0
    rate = (assumptions['stress_interest'] if stressed
            else assumptions['pricing_interest'])
    multiplier = (assumptions['stress_mortality_multiplier'] if stressed else 1.0)
    a, A = factors(age + t, term - t, rate, q_by_age, multiplier)

    if t == 0:
        future_expenses = (assumptions['initial_fixed_expense']
                           + assumptions['initial_premium_pct'] * premium
                           + (assumptions['renewal_fixed_expense']
                              + assumptions['renewal_premium_pct'] * premium) * (a - 1))
    else:
        future_expenses = (assumptions['renewal_fixed_expense']
                           + assumptions['renewal_premium_pct'] * premium) * a
    return sum_assured * A + future_expenses - premium * a


def retrospective_reserves(age, term, sum_assured, premium, assumptions, q_by_age):
    """Forward recursion per surviving policy on the pricing basis."""
    rate = assumptions['pricing_interest']
    values = [0.0]
    for year in range(term - 1):
        expense = (assumptions['initial_fixed_expense']
                   + assumptions['initial_premium_pct'] * premium) if year == 0 else (
                   assumptions['renewal_fixed_expense']
                   + assumptions['renewal_premium_pct'] * premium)
        q = q_by_age[age + year]
        p = 1 - q
        next_reserve = ((values[-1] + premium - expense) * (1 + rate)
                        - q * sum_assured) / p
        values.append(next_reserve)
    values.append(0.0)
    return values


def load_input(path):
    """Read the three editable Excel input sheets and validate their values."""
    ass_df = pd.read_excel(path, sheet_name='Assumptions')
    port = pd.read_excel(path, sheet_name='Portfolio')
    mort = pd.read_excel(path, sheet_name='Mortality')
    assumptions = dict(zip(ass_df['Parameter'], ass_df['Value']))
    needed = ['pricing_interest', 'initial_fixed_expense', 'initial_premium_pct',
              'renewal_fixed_expense', 'renewal_premium_pct', 'stress_interest',
              'stress_mortality_multiplier']
    for key in needed:
        if key not in assumptions or pd.isna(assumptions[key]):
            raise ValueError(f'Missing assumption: {key}')
    for key in ['pricing_interest', 'stress_interest']:
        if not (-0.99 < float(assumptions[key]) < 1):
            raise ValueError(f'Interest rate out of range: {key}')
    if not (0 <= float(assumptions['initial_premium_pct']) < 1):
        raise ValueError('Initial premium percentage must be in [0,1)')
    if not (0 <= float(assumptions['renewal_premium_pct']) < 1):
        raise ValueError('Renewal premium percentage must be in [0,1)')
    if float(assumptions['stress_mortality_multiplier']) <= 0:
        raise ValueError('Stress mortality multiplier must be positive')
    for key in ['initial_fixed_expense', 'renewal_fixed_expense']:
        if float(assumptions[key]) < 0:
            raise ValueError(f'Expense cannot be negative: {key}')
    assumptions = {k: float(v) for k, v in assumptions.items()}

    required_cols = {'Cohort_ID', 'Issue_Year', 'Entry_Age', 'Term_Years',
                     'Sum_Assured_INR', 'Policies_Issued'}
    if not required_cols.issubset(port.columns):
        raise ValueError(f'Portfolio sheet must have: {sorted(required_cols)}')
    if port.empty or port['Cohort_ID'].duplicated().any():
        raise ValueError('Portfolio cannot be empty and Cohort_ID must be unique')
    if mort['Age'].duplicated().any() or not mort['Age'].notna().all():
        raise ValueError('Mortality ages must be present and unique')
    if not mort['qx'].between(0, 0.999).all():
        raise ValueError('Mortality qx values must lie between 0 and 0.999')
    q_by_age = dict(zip(mort['Age'].astype(int), mort['qx'].astype(float)))
    return assumptions, port, q_by_age


def build_results(assumptions, portfolio, q_by_age):
    premium_rows = []
    detail_rows = []
    check_rows = []
    for item in portfolio.to_dict('records'):
        code = str(item['Cohort_ID'])
        age, term = int(item['Entry_Age']), int(item['Term_Years'])
        issue, count = int(item['Issue_Year']), int(item['Policies_Issued'])
        amount = float(item['Sum_Assured_INR'])
        if age < 0 or term < 1 or count <= 0 or amount <= 0:
            raise ValueError(f'Invalid age, term, count or benefit: {code}')
        missing = [x for x in range(age, age + term) if x not in q_by_age]
        if missing:
            raise ValueError(f'Missing mortality ages for {code}: {missing}')
        premium, a, A = gross_premium(amount, age, term, assumptions, q_by_age)
        old = retrospective_reserves(age, term, amount, premium, assumptions, q_by_age)
        premium_rows.append({'Cohort_ID': code, 'Entry_Age': age, 'Term_Years': term,
                             'Annuity_Due_Factor': a, 'Endowment_Factor': A,
                             'Annual_Gross_Premium_INR': premium,
                             'Annual_Renewal_Expense_INR': assumptions['renewal_fixed_expense']
                             + assumptions['renewal_premium_pct'] * premium})
        survivor_fraction = 1.0
        greatest_diff = 0.0
        for t in range(term):
            base = prospective_reserve(t, age, term, amount, premium, assumptions, q_by_age)
            stress = prospective_reserve(t, age, term, amount, premium, assumptions,
                                         q_by_age, stressed=True)
            diff = abs(base - old[t])
            greatest_diff = max(greatest_diff, diff)
            expected_alive = survivor_fraction * count
            detail_rows.append({
                'Cohort_ID': code, 'Valuation_Year': issue + t,
                'Policy_Duration_t': t, 'Attained_Age': age + t,
                'Expected_Policies_In_Force': expected_alive,
                'Annual_Gross_Premium_INR': premium,
                'Prospective_per_Policy_INR': base,
                'Retrospective_per_Policy_INR': old[t],
                'Stress_Prospective_per_Policy_INR': stress,
                'Base_Total_Reserve_INR': base * expected_alive,
                'Stress_Total_Reserve_INR': stress * expected_alive,
                'Pro_Retro_Absolute_Difference_INR': diff})
            survivor_fraction *= 1 - q_by_age[age + t]
        check_rows.append({'Cohort_ID': code, 'Max_Pro_Retro_Diff_INR': greatest_diff,
                           'Pass_Tolerance_0.01_INR': 'PASS' if greatest_diff < 0.01 else 'FAIL'})

    detail = pd.DataFrame(detail_rows).sort_values(['Valuation_Year', 'Cohort_ID'])
    yearly = detail.groupby('Valuation_Year', as_index=False).agg(
        Expected_Policies_In_Force=('Expected_Policies_In_Force', 'sum'),
        Base_Reserve_INR=('Base_Total_Reserve_INR', 'sum'),
        Stress_Reserve_INR=('Stress_Total_Reserve_INR', 'sum'))
    yearly['Stress_Minus_Base_INR'] = yearly['Stress_Reserve_INR'] - yearly['Base_Reserve_INR']
    yearly['Base_Reserve_Crore_INR'] = yearly['Base_Reserve_INR'] / 10_000_000
    return pd.DataFrame(premium_rows), detail, yearly, pd.DataFrame(check_rows)


def export_results(output_dir, assumptions, premiums, detail, yearly, checks):
    output_dir.mkdir(parents=True, exist_ok=True)
    excel_path = output_dir / 'gross_premium_reserves_output.xlsx'
    notes = pd.DataFrame([
        ('Model', 'Without-profits annual-premium endowment assurance; benefit paid at end of year of death or at maturity.'),
        ('Timing', 'Reserves at duration t: before the premium and expenses due at t, after previous year-end benefits.'),
        ('Premium', 'Calculated from EPV premiums = EPV benefits + EPV initial and renewal expenses.'),
        ('Gross prospective', 'EPV future benefits + EPV future expenses - EPV future gross premiums.'),
        ('Gross retrospective', 'Accumulated past gross premiums - past benefits/expenses, per surviving policy.'),
        ('Same basis check', 'Pricing, base prospective, and retrospective all use one mortality/interest/expense basis.'),
        ('Stress scenario', f"Interest {assumptions['stress_interest']:.1%}; future mortality multiplied by {assumptions['stress_mortality_multiplier']:.2f}."),
        ('Expected in force', 'Expected survivor counts, not observed actual policy counts.'),
        ('Currency', 'INR, nominal; crore = INR 10,000,000.'),
        ('Mortality data', 'Synthetic demonstration qx rates; NOT AM92/real insurer mortality data.'),
        ('Scope limitation', 'Educational deterministic reserve calculation, not regulatory or statutory capital reporting.'),
        ('End of contract', 'No reserve appears at duration n because maturity benefits have already been paid.'),
    ], columns=['Concept', 'Meaning'])
    with pd.ExcelWriter(excel_path, engine='openpyxl') as writer:
        notes.to_excel(writer, sheet_name='Guide', index=False)
        premiums.round(6).to_excel(writer, sheet_name='Premium_Calculation', index=False)
        detail.round(6).to_excel(writer, sheet_name='Policy_Year_Reserves', index=False)
        yearly.round(6).to_excel(writer, sheet_name='Yearly_Company_Reserves', index=False)
        checks.round(8).to_excel(writer, sheet_name='Validation_Checks', index=False)

    fig, ax = plt.subplots(figsize=(9, 4.5))
    ax.plot(yearly['Valuation_Year'], yearly['Base_Reserve_INR'] / 10_000_000,
            label='Base', linewidth=2, marker='o', markersize=4)
    ax.plot(yearly['Valuation_Year'], yearly['Stress_Reserve_INR'] / 10_000_000,
            label='Stress', linewidth=2, linestyle='--')
    ax.set_title('Life Insurance Gross Premium Reserve by Valuation Year')
    ax.set_xlabel('Calendar year')
    ax.set_ylabel('Company reserve (INR crore)')
    ax.grid(alpha=0.25)
    ax.legend()
    fig.tight_layout()
    fig.savefig(output_dir / 'year_wise_reserves.png', dpi=170)
    plt.close(fig)
    return excel_path


def main():
    parser = argparse.ArgumentParser(description='CM1 gross premium reserve calculator')
    parser.add_argument('--input', type=Path, default=DEFAULT_INPUT)
    parser.add_argument('--output-dir', type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    assumptions, portfolio, mortality = load_input(args.input)
    premiums, detail, yearly, checks = build_results(assumptions, portfolio, mortality)
    if not (checks['Pass_Tolerance_0.01_INR'] == 'PASS').all():
        raise RuntimeError('Prospective/retrospective reconciliation failed')
    path = export_results(args.output_dir, assumptions, premiums, detail, yearly, checks)
    peak = yearly.loc[yearly['Base_Reserve_INR'].idxmax()]
    print(f'Output workbook: {path}')
    print(f'Peak base portfolio reserve: INR {peak.Base_Reserve_INR:,.2f} in {int(peak.Valuation_Year)}')
    print(f'Prospective vs retrospective: PASS for all {len(checks)} cohorts')


if __name__ == '__main__':
    main()
