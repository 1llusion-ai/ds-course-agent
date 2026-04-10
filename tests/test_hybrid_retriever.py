from core.hybrid_retriever import BM25Retriever, _normalize_latin_tokens


def test_normalize_latin_tokens_uppercases_acronyms():
    assert _normalize_latin_tokens("pca的公式 是什么？") == "PCA的公式 是什么？"
    assert _normalize_latin_tokens("svm kernel怎么选") == "SVM KERNEL怎么选"


def test_tokenize_treats_lowercase_acronyms_as_textbook_terms():
    retriever = BM25Retriever()

    assert retriever._tokenize("pca的公式 是什么？") == ["PCA", "公式", "什么"]
    assert retriever._tokenize("svm是什么？") == ["SVM", "什么"]
