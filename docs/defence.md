# Interview defence sheet

Questions an interviewer is likely to ask about Stagecraft, grouped by topic. Answers are deliberately left blank:
write your own, in your words, then rehearse them out loud.

---

## IFRS 9 concepts

1. What is the difference between the IAS 39 incurred-loss model and IFRS 9 expected credit loss? Why did the change happen?

   &nbsp;

2. Why is Stage 1 a 12-month ECL and Stage 2 a lifetime ECL? What is the economic logic of the step-up?

   &nbsp;

3. What does "probability-weighted, unbiased" mean in IFRS 9 5.5.17, and how does your model meet it?

   &nbsp;

4. Why discount at the effective interest rate, and what does using the note rate as a proxy miss?

   &nbsp;

5. What is a management overlay, when is one justified, and how should it be governed?

   &nbsp;

## SICR and staging

6. Walk me through your Stage 2 criteria. Which one does most of the work, and why?

   &nbsp;

7. Why use both a relative (2×) and an absolute (50bp) threshold for SICR?

   &nbsp;

8. What is the cliff effect? Your sensitivity barely moves when you change the threshold; is that good or bad?

   &nbsp;

9. How did you get an origination PD for loans written in 2005 when you built the model in 2018?

   &nbsp;

10. Why keep cured loans in Stage 3 for six months? What would RBI norms on NPA upgrades say?

    &nbsp;

11. Should a forborne or modified loan always be Stage 2? When might you rebut that?

    &nbsp;

## PD modelling

12. Explain your hazard model's design: why snapshot × horizon rather than a plain loan-month panel?

    &nbsp;

13. How do macro variables enter the PD, and how did you avoid look-ahead?

    &nbsp;

14. Why build a Markov roll-rate challenger? What are its weaknesses?

    &nbsp;

15. How do you turn monthly hazards into 12-month and lifetime PDs without double counting prepayment?

    &nbsp;

16. Why constrain the age effect beyond six years? Isn't that overriding the data?

    &nbsp;

17. Point-in-time vs through-the-cycle PD: which does IFRS 9 want, and which is your model?

    &nbsp;

## LGD and EAD

18. How did you compute LGD from Freddie Mac's loss fields? Accounting vs economic LGD?

    &nbsp;

19. Why is Stage 3 coverage only about 26% for mortgages, compared with 60%+ for an unsecured book?

    &nbsp;

20. How does LGD respond to the scenarios? What would you add with more data?

    &nbsp;

21. What is your cure-rate adjustment, and what could go wrong with it?

    &nbsp;

22. How did you model EAD and prepayment, and how would a rate shock change them?

    &nbsp;

## Scenarios and weights

23. How did you choose the base, upside and downside paths and the 60/20/20 weights? Who should own them?

    &nbsp;

24. Why is weighted ECL above base ECL? Could it ever be below?

    &nbsp;

25. Why is the severe scenario excluded from the weighted ECL?

    &nbsp;

26. If you had to update the scenarios in March 2020, what would you change, and how fast?

    &nbsp;

## Validation

27. Your 31 Dec 2019 backtest is red. Is the model broken?

    &nbsp;

28. How do you read AUC/Gini for a low-default portfolio? What is a good number?

    &nbsp;

29. Explain the provision movement waterfall. How do you separate a stage transfer from a remeasurement?

    &nbsp;

30. What would an independent validator challenge first in this model?

    &nbsp;

## Data limitations

31. What is in, and not in, the Freddie Mac sample? How does that bias the results?

    &nbsp;

32. Why can't you see 1–29 days-past-due accounts, and does it matter?

    &nbsp;

33. The public repo can't hold Freddie Mac loan-level data. How would someone reproduce your results, and what does the demo mode show?

    &nbsp;

## India / RBI relevance

34. What do the RBI's 2026 ECL Directions require, and from when? Which banks are in scope?

    &nbsp;

35. Map Freddie Mac's delinquency status onto SMA-0/1/2 and NPA. Where do the counting conventions differ?

    &nbsp;

36. The RBI's Stage 1 floor for housing loans is 0.25%. Your model says 0.10%. What does a bank book, and what is the
    point of the model then?

    &nbsp;

37. How would you build this for an Indian cooperative bank's gold loan or MSME book?

    &nbsp;
