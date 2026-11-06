"""User-facing feature labels (EN/HI) and the chatbot knowledge base. Model facts are read from the trained model's metadata,
never hard-coded, so the assistant cannot drift from the deployed model."""
from __future__ import annotations

import re

FEATURES = {
    "RevolvingUtilizationOfUnsecuredLines": ("Credit utilisation", "क्रेडिट उपयोग अनुपात (Credit utilisation)", "Share of your revolving credit limits currently used (cards, personal lines).", "आपकी रिवॉल्विंग क्रेडिट सीमा का कितना हिस्सा उपयोग में है (कार्ड, पर्सनल लाइन)।"),
    "age": ("Age", "आयु (Age)", "Applicant age in years.", "आवेदक की आयु (वर्षों में)।"),
    "MonthlyIncome": ("Monthly income", "मासिक आय (Monthly income)", "Gross monthly income. May be left blank.", "सकल मासिक आय। खाली छोड़ी जा सकती है।"),
    "NumberOfOpenCreditLinesAndLoans": ("Open credit lines & loans", "खुली क्रेडिट लाइन व ऋण", "Count of open loans and credit lines.", "खुले ऋण और क्रेडिट लाइनों की संख्या।"),
    "NumberRealEstateLoansOrLines": ("Real-estate loans", "रियल-एस्टेट ऋण", "Mortgage and home-equity loans or lines.", "होम लोन/मॉर्गेज और होम-इक्विटी लाइनें।"),
    "NumberOfDependents": ("Dependents", "आश्रित (Dependents)", "People financially dependent on the applicant. May be left blank.", "आवेदक पर आर्थिक रूप से निर्भर लोग। खाली छोड़ा जा सकता है।"),
    "NumberOfTime30-59DaysPastDueNotWorse": ("Times 30–59 days late", "30–59 दिन देरी की बार", "Times payment was 30–59 days overdue in the last 2 years.", "पिछले 2 वर्षों में 30–59 दिन देरी से भुगतान की बार।"),
    "NumberOfTime60-89DaysPastDueNotWorse": ("Times 60–89 days late", "60–89 दिन देरी की बार", "Times payment was 60–89 days overdue in the last 2 years.", "पिछले 2 वर्षों में 60–89 दिन देरी से भुगतान की बार।"),
    "NumberOfTimes90DaysLate": ("Times 90+ days late", "90+ दिन देरी की बार", "Times payment was 90 or more days overdue.", "90 या अधिक दिन देरी से भुगतान की बार।"),
    "income_reported": ("Income reported", "आय दर्ज की गई", "Whether a monthly income above zero was provided.", "क्या शून्य से अधिक मासिक आय दी गई।"),
    "debt_ratio_valid": ("Debt-to-income ratio", "ऋण-आय अनुपात (Debt-to-income)", "Monthly debt payments and living costs divided by monthly income (needs income).", "मासिक ऋण भुगतान और खर्च ÷ मासिक आय (आय आवश्यक)।"),
    "est_monthly_obligations": ("Estimated monthly obligations", "अनुमानित मासिक देनदारियाँ", "Debt-to-income ratio × monthly income.", "ऋण-आय अनुपात × मासिक आय।"),
    "income_per_household_member": ("Income per household member", "प्रति सदस्य आय", "Monthly income ÷ (dependents + 1).", "मासिक आय ÷ (आश्रित + 1)।"),
    "total_past_due_events": ("Total late-payment events", "कुल देरी की घटनाएँ", "Sum of the three late-payment counts.", "तीनों देरी-गणनाओं का योग।"),
    "has_90plus_delinquency": ("Any 90+ day delinquency", "कोई 90+ दिन की चूक", "1 if any payment was 90+ days late.", "यदि कोई भुगतान 90+ दिन देर से हुआ तो 1।"),
    "utilization_over_limit": ("Credit used above limit", "सीमा से अधिक उपयोग", "1 if utilisation is above 100% of the limit.", "यदि उपयोग सीमा के 100% से अधिक है तो 1।"),
}


def feature_payload() -> dict:
    return {k: {"en": {"label": v[0], "desc": v[2]}, "hi": {"label": v[1], "desc": v[3]}} for k, v in FEATURES.items()}


def _pct(x: float) -> str:
    return f"{100 * x:.1f}%"


def build_kb(meta: dict | None) -> list[dict]:
    """Each entry: id, kw (keywords), en, hi."""
    kb = [
        dict(id="platform", kw="arthsetu platform what is how works overview assessment",
             en="ArthSetu is an alternative credit-risk decision-support platform. You enter applicant details, a machine-learning model estimates the probability of serious delinquency (90+ days past due) within 2 years, and an explanation shows which inputs pushed the estimate up or down. It is not a loan approval system.",
             hi="ArthSetu एक वैकल्पिक क्रेडिट-जोखिम निर्णय-सहायता प्लेटफ़ॉर्म है। आप विवरण दर्ज करते हैं, मॉडल 2 वर्षों में गंभीर चूक (90+ दिन देरी) की संभावना का अनुमान देता है, और व्याख्या बताती है कि किन इनपुट ने अनुमान बढ़ाया या घटाया। यह ऋण स्वीकृति प्रणाली नहीं है।"),
        dict(id="default_prob", kw="default probability approval approve loan meaning probability risk",
             en="The default probability is the model's estimate that a borrower with this profile becomes 90+ days delinquent within 2 years. It is NOT the probability a loan is approved, and not a guarantee about any individual.",
             hi="डिफ़ॉल्ट प्रायिकता मॉडल का अनुमान है कि ऐसी प्रोफ़ाइल वाला उधारकर्ता 2 वर्षों में 90+ दिन चूक करेगा। यह ऋण स्वीकृति की संभावना नहीं है और किसी व्यक्ति के लिए गारंटी नहीं है।"),
        dict(id="alt_credit", kw="alternative credit scoring alternative data msme thin file",
             en="Alternative credit scoring uses signals beyond a traditional bureau score (for example cash-flow, bill payments or transactions) to assess borrowers with thin credit files. IMPORTANT: this prototype is trained on a US consumer credit dataset that has no such alternative-data fields, so it does not yet do true alternative scoring for Indian MSMEs.",
             hi="वैकल्पिक क्रेडिट स्कोरिंग पारंपरिक ब्यूरो स्कोर के अलावा संकेतों (जैसे कैश-फ़्लो, बिल भुगतान, लेन-देन) का उपयोग करती है। महत्वपूर्ण: यह प्रोटोटाइप अमेरिकी उपभोक्ता क्रेडिट डेटा पर प्रशिक्षित है जिसमें ऐसे फ़ील्ड नहीं हैं, इसलिए यह अभी भारतीय MSME के लिए वास्तविक वैकल्पिक स्कोरिंग नहीं करता।"),
        dict(id="limits", kw="limitations limitation india indian msme data bias fairness leakage age caution reliable",
             en="Limitations: (1) trained on the public 'Give Me Some Credit' US consumer dataset (2011), not Indian borrowers or MSMEs; (2) the data has no timestamps, so the 90-days-late count may leak information close to the target; (3) age is an input, which raises fairness concerns; (4) outputs are statistical estimates for decision support only.",
             hi="सीमाएँ: (1) मॉडल अमेरिकी उपभोक्ता डेटासेट (2011) पर प्रशिक्षित है, भारतीय उधारकर्ताओं/MSME पर नहीं; (2) डेटा में समय-चिह्न नहीं हैं, इसलिए 90-दिन देरी की संख्या लक्ष्य से जुड़ी जानकारी ले सकती है; (3) आयु एक इनपुट है, जिससे निष्पक्षता की चिंता है; (4) आउटपुट केवल सांख्यिकीय अनुमान हैं।"),
        dict(id="explain_read", kw="explanation shap shapley contribution factor why reading feature impact causation correlation",
             en="Each bar shows how much a feature moved this applicant's estimated default probability, in percentage points, relative to an average reference profile. Red/up = raised risk, green/down = lowered risk. These are model contributions, not causes: they describe what the model learned from correlations in past data, not what would happen if you changed the input.",
             hi="हर बार दर्शाता है कि किसी फ़ीचर ने औसत संदर्भ प्रोफ़ाइल की तुलना में इस आवेदक की अनुमानित डिफ़ॉल्ट प्रायिकता को कितने प्रतिशत-अंक खिसकाया। ऊपर/लाल = जोखिम बढ़ा, नीचे/हरा = घटा। ये मॉडल के योगदान हैं, कारण नहीं।"),
        dict(id="shapley_method", kw="shap shapley method estimator algorithm library",
             en="Explanations are Shapley values of the deployed model's output, estimated by permutation sampling against a background sample of training rows. They are exactly additive (base value + contributions = prediction) but, because they are sampled, each has a small standard error. This is not the `shap` library's TreeExplainer (that package was not available when the platform was built).",
             hi="व्याख्याएँ तैनात मॉडल के आउटपुट के Shapley मान हैं, जिन्हें प्रशिक्षण पंक्तियों के पृष्ठभूमि नमूने पर क्रमचय-नमूनाकरण से आँका जाता है। ये पूरी तरह योगात्मक हैं; नमूनाकरण के कारण हर मान में छोटी मानक त्रुटि होती है। यह `shap` लाइब्रेरी का TreeExplainer नहीं है।"),
        dict(id="glossary_dti", kw="debt-to-income dti debt ratio income obligations",
             en="Debt-to-income (DTI) ratio = monthly debt payments (and living costs in this dataset) ÷ monthly gross income. Higher values mean less room to absorb a new repayment.",
             hi="ऋण-आय अनुपात (DTI) = मासिक ऋण भुगतान (और इस डेटासेट में जीवन-व्यय) ÷ मासिक सकल आय। उच्च मान का अर्थ नई किस्त के लिए कम गुंजाइश है।"),
        dict(id="glossary_util", kw="credit utilisation utilization revolving limit card balance",
             en="Credit utilisation = revolving balances ÷ total revolving credit limits. Using most of your limits is typically associated with higher stress and higher default risk.",
             hi="क्रेडिट उपयोग = रिवॉल्विंग बकाया ÷ कुल रिवॉल्विंग सीमा। अधिकांश सीमा का उपयोग प्रायः अधिक तनाव और अधिक चूक-जोखिम से जुड़ा होता है।"),
        dict(id="glossary_dpd", kw="delinquency delinquent past due dpd late payment overdue 30 60 90",
             en="Delinquency means a payment is overdue. '30–59 / 60–89 / 90+ days past due' (DPD) buckets show severity; 90+ days is a serious delinquency and is also how this model's target is defined.",
             hi="चूक का अर्थ भुगतान में देरी है। '30–59 / 60–89 / 90+ दिन' (DPD) गंभीरता दर्शाते हैं; 90+ दिन गंभीर चूक है और इसी से इस मॉडल का लक्ष्य परिभाषित है।"),
        dict(id="glossary_metrics", kw="roc-auc auc pr-auc precision recall f1 brier calibration accuracy specificity metrics confusion",
             en="ROC-AUC measures how well the model ranks defaulters above non-defaulters (0.5 = chance). PR-AUC focuses on the rare default class. Precision = of those flagged, how many truly default; recall = of true defaulters, how many are flagged. Calibration checks that a predicted 10% really means about 10%; the Brier score measures that. Accuracy alone misleads when defaults are rare.",
             hi="ROC-AUC मापता है कि मॉडल चूककर्ताओं को कितनी अच्छी तरह ऊपर रैंक करता है (0.5 = संयोग)। PR-AUC दुर्लभ चूक वर्ग पर केंद्रित है। Precision = चिह्नित में से कितने सच में चूक करते हैं; recall = वास्तविक चूककर्ताओं में से कितने चिह्नित हुए। Calibration जाँचता है कि 10% का अर्थ लगभग 10% है। चूक दुर्लभ हो तो केवल accuracy भ्रामक है।"),
        dict(id="xgboost", kw="xgboost gradient boosting trees ensemble",
             en="Gradient boosting builds many small decision trees one after another, each correcting the previous trees' errors. XGBoost is one popular implementation.",
             hi="ग्रेडिएंट बूस्टिंग कई छोटे निर्णय-वृक्ष क्रम से बनाती है, हर वृक्ष पिछले की त्रुटियाँ सुधारता है। XGBoost एक लोकप्रिय कार्यान्वयन है।"),
        dict(id="smote", kw="smote oversampling imbalance imbalanced class resampling synthetic",
             en="SMOTE creates synthetic minority-class examples by interpolating between real minority neighbours, to counter class imbalance. It must be applied only to training folds, never to validation or test data.",
             hi="SMOTE वर्ग-असंतुलन के लिए वास्तविक अल्पसंख्यक पड़ोसियों के बीच अंतर्वेशन से कृत्रिम उदाहरण बनाता है। इसे केवल प्रशिक्षण फ़ोल्ड पर लागू करें, सत्यापन/परीक्षण डेटा पर कभी नहीं।"),
        dict(id="privacy", kw="privacy data stored security sensitive personal chatbot groq",
             en="Your assessments are stored in your own account and are visible only to you (administrators can see aggregate monitoring and audit events, not your financial inputs). The assistant never receives your inputs: only your question, the page you are on, and at most the risk band and names of top factors.",
             hi="आपके आकलन आपके खाते में संग्रहीत हैं और केवल आपको दिखते हैं (प्रशासक समेकित निगरानी और ऑडिट घटनाएँ देख सकते हैं, आपके वित्तीय इनपुट नहीं)। सहायक को आपके इनपुट नहीं मिलते: केवल प्रश्न, पृष्ठ और अधिकतम जोखिम श्रेणी व शीर्ष कारकों के नाम।"),
        dict(id="features", kw="features inputs fields definitions variables list what data",
             en="Model inputs: " + "; ".join(f"{v[0]} — {v[2]}" for v in FEATURES.values()),
             hi="मॉडल इनपुट: " + "; ".join(f"{v[1]} — {v[3]}" for v in FEATURES.values())),
    ]
    if meta:
        t, cv = meta["test"], meta["cv_5fold_train_oof"]
        algo = meta["algorithm"]
        cvtxt = "; ".join(f"{k}: PR-AUC {v['oof_pr_auc']:.3f}" for k, v in cv.items())
        kb += [
            dict(id="model", kw="model algorithm which trained version dataset deployed what model used",
                 en=f"Deployed model {meta['model_version']} (dataset {meta['dataset_version']}): {algo.replace('_', ' ')}, probabilities calibrated with isotonic regression, {len(meta['features'])} input features, random seed {meta['random_seed']}, split policy: {meta['split_policy']}. XGBoost status: {meta['xgboost_smote_status']}.",
                 hi=f"तैनात मॉडल {meta['model_version']} (डेटासेट {meta['dataset_version']}): {algo.replace('_', ' ')}, isotonic regression से कैलिब्रेटेड प्रायिकताएँ, {len(meta['features'])} फ़ीचर, seed {meta['random_seed']}। XGBoost स्थिति: {meta['xgboost_smote_status']}।"),
            dict(id="model_metrics", kw="metrics accuracy auc precision recall f1 performance test results how good",
                 en=f"Held-out test results ({t['n']:,} applicants, {t['positives']:,} defaults, threshold {t['threshold']:.3f}): ROC-AUC {t['roc_auc']:.3f}, PR-AUC {t['pr_auc']:.3f}, precision {_pct(t['precision'])}, recall {_pct(t['recall'])}, F1 {t['f1']:.3f}, accuracy {_pct(t['accuracy'])}, Brier {t['brier']:.4f}. Accuracy is inflated by the rare default class (~{_pct(1 - meta['base_rate_train'])} are non-defaults); the model misses about {_pct(t['false_negative_rate'])} of true defaulters at this threshold.",
                 hi=f"होल्ड-आउट परीक्षण ({t['n']:,} आवेदक, {t['positives']:,} चूक, थ्रेशोल्ड {t['threshold']:.3f}): ROC-AUC {t['roc_auc']:.3f}, PR-AUC {t['pr_auc']:.3f}, precision {_pct(t['precision'])}, recall {_pct(t['recall'])}, F1 {t['f1']:.3f}, accuracy {_pct(t['accuracy'])}। चूक दुर्लभ होने से accuracy बढ़ी दिखती है; इस थ्रेशोल्ड पर मॉडल लगभग {_pct(t['false_negative_rate'])} वास्तविक चूककर्ताओं को चूक जाता है।"),
            dict(id="smote_result", kw="smote result comparison cross validation selected resampling candidates compare",
                 en=f"Candidate comparison by 5-fold out-of-fold cross-validation on the 80% training set — {cvtxt}. The selected model is {algo.replace('_', ' ')}. SMOTE, when used, was applied only inside training folds.",
                 hi=f"80% प्रशिक्षण सेट पर 5-फ़ोल्ड क्रॉस-वैलिडेशन तुलना — {cvtxt}। चयनित मॉडल: {algo.replace('_', ' ')}। SMOTE केवल प्रशिक्षण फ़ोल्ड के भीतर लागू हुआ।"),
            dict(id="risk_bands", kw="risk band category low moderate high threshold meaning",
                 en=f"Risk bands from the calibrated probability: LOW below {_pct(meta['risk_bands']['low_max'])}; HIGH at or above {_pct(meta['risk_bands']['high_min'])} (the F1-optimal flagging threshold chosen on training data); MODERATE in between. The average default rate in the training data is {_pct(meta['base_rate_train'])}.",
                 hi=f"कैलिब्रेटेड प्रायिकता से जोखिम श्रेणी: LOW {_pct(meta['risk_bands']['low_max'])} से कम; HIGH {_pct(meta['risk_bands']['high_min'])} या अधिक; बीच में MODERATE। प्रशिक्षण डेटा में औसत चूक दर {_pct(meta['base_rate_train'])} है।"),
        ]
    return kb


PAGE_HINTS = {
    "assess": "The user is filling the assessment form: explain fields and terms.",
    "result": "The user is viewing a prediction result: explain probability, risk band, and the explanation bars.",
    "dashboard": "The user is on the dashboard: explain what the platform offers.",
    "history": "The user is browsing past assessments.", "model": "The user is viewing model information and metrics.",
    "settings": "The user is on account settings.", "admin": "The user is an administrator viewing monitoring pages.", "landing": "The user is on the landing page.",
}

_tok = re.compile(r"[\w\-]+", re.UNICODE)


def retrieve(kb: list[dict], query: str, k: int = 3) -> list[dict]:
    q = {t for t in _tok.findall(query.lower()) if len(t) > 2}
    scored = []
    for e in kb:
        words = set(_tok.findall(e["kw"].lower()))
        text = set(_tok.findall(e["en"].lower()))
        s = 3 * len(q & words) + len(q & text)
        if s:
            scored.append((s, e))
    scored.sort(key=lambda t: -t[0])
    return [e for _, e in scored[:k]]
