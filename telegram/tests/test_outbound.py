from shellm_telegram.outbound import RecentPosts


def test_recent_posts_dedupe_window():
    recent = RecentPosts(window=300)
    assert not recent.is_duplicate("telegram-1-1", "hi", now=0)
    assert recent.is_duplicate("telegram-1-1", "hi", now=100)
    assert not recent.is_duplicate("telegram-1-1", "hi", now=500)
    assert not recent.is_duplicate("telegram-2-2", "hi", now=100)
