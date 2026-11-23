# Escalation Report

## Summary
Processed 12 loan applications on $(date). 7 applications passed AML checks and were approved. 5 applications failed AML checks and could not be approved per policy.

## Failed Applications

- **application_002.json**: R1 – fund_source 'Unknown' is not a documented source of funds.
- **application_003.json**: R2 – transaction of 50000.00 on 2023-01-10 >= 10000 has no matching CTR filing.
- **application_006.json**: R4 – sanctions match: 'Volkov Trading FZE' matches listed entity 'VOLKOV TRADING F.Z.E.'.
- **application_007.json**: R3 – possible structuring: 4 cash deposits between 8000 and 10000 within 7 days.
- **application_008.json**: R5 – KYC expired on 2022-12-31 (application dated 2023-03-01).

## Recommendations
All failed applications require manual review by compliance officers. No overrides were submitted as per policy. Consider contacting the applicants for remediation where possible.
