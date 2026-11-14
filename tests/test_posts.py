import asyncio

from terminal import posts

TWEET = {"__typename": "Tweet", "favorite_count": 2126, "conversation_count": 113, "id_str": "2120971125412827486",
         "text": "Bloomberg reports the board met late into the night https://t.co/abc",
         "user": {"screen_name": "StockSavvyShay", "is_blue_verified": True}}


def test_a_post_on_x_is_read_from_what_x_serves_for_embedding():
    assert posts.parse_x(TWEET) == {"handle": "StockSavvyShay", "likes": 2126, "replies": 113, "is_reply": False,
                                    "text": "Bloomberg reports the board met late into the night https://t.co/abc"}
    assert posts.parse_x({**TWEET, "in_reply_to_status_id_str": "1"})["is_reply"] is True
    assert posts.parse_x({"__typename": "TweetTombstone"}) is None  # deleted or withheld


def post(**kw):
    return {**posts.parse_x(TWEET), **kw}


def test_replies_bare_links_and_old_posts_nobody_liked_are_trash():
    hour = 3600
    assert not posts.x_trash(post(), 5 * hour)
    assert posts.x_trash(post(is_reply=True), 5 * hour)
    assert posts.x_trash(post(text="https://t.co/YZbF6H4GmH"), 5 * hour)
    assert posts.x_trash(post(text="@someone thanks https://t.co/x"), 5 * hour)
    assert posts.x_trash(post(likes=19), 2 * hour)
    assert not posts.x_trash(post(likes=20), 2 * hour)
    assert not posts.x_trash(post(likes=0), 0.5 * hour)  # too new to have been liked yet
    assert posts.x_trash(post(likes=0), None)  # age unknown: judged as old


def test_reddit_listing_pages_recurring_threads_and_removed_posts_are_trash():
    url = "https://www.reddit.com/r/stocks/comments/1xv4fs0/a_post/"
    assert not posts.reddit_trash(url, "Fed signals a December hike")
    assert posts.reddit_trash("https://www.reddit.com/r/stocks/?after=dDNf&sort=best&t=DAY", "r/stocks")
    for title in ("r/Stocks Daily Discussion & Fundamentals Friday Nov 13, 2026", "SoFi Daily Chat - November 13, 2026",
                  "Daily Thread and Discussion 2026-11-13 Friday", "Weekly megathread", "[ Removed by moderator ]",
                  "[removed]", "[deleted by user]"):
        assert posts.reddit_trash(url, title), title


FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"><title>newest submissions : nvidia</title>
<entry><author><name>/u/someone</name></author>
<content type="html">&lt;div class="md"&gt;&lt;p&gt;The board &amp;amp; Ian Buck met.&lt;/p&gt;&lt;/div&gt; &amp;#32; submitted by &amp;#32; &lt;a href="https://www.reddit.com/user/someone"&gt; /u/someone &lt;/a&gt; &lt;br/&gt; &lt;span&gt;&lt;a href="https://example.com/a"&gt;[link]&lt;/a&gt;&lt;/span&gt; &lt;span&gt;&lt;a href="https://www.reddit.com/r/nvidia/comments/1abc/board_meets/"&gt;[comments]&lt;/a&gt;&lt;/span&gt;</content>
<id>t3_1abc</id><link href="https://www.reddit.com/r/nvidia/comments/1abc/board_meets/" />
<updated>2026-11-14T00:16:25+00:00</updated><published>2026-11-14T00:16:25+00:00</published>
<title>Board meets over the next CEO</title></entry>
<entry><link href="https://www.reddit.com/r/nvidia/comments/1abd/no_time/" /><title>No time on this one</title></entry>
</feed>"""


def test_a_subreddit_feed_gives_each_post_with_its_time_and_text():
    assert posts.parse_feed(FEED) == [
        {"url": "https://www.reddit.com/r/nvidia/comments/1abc/board_meets/", "title": "Board meets over the next CEO",
         "description": "The board & Ian Buck met.", "published": 1794615385.0},
        {"url": "https://www.reddit.com/r/nvidia/comments/1abd/no_time/", "title": "No time on this one",
         "description": "", "published": None}]


def test_a_post_is_worth_scoring_only_if_it_shares_a_word_with_the_markets_queries():
    queries = ["Ian Buck Nvidia CEO", "Nvidia board latest news 2026"]
    assert posts.shares_words("Buck seen at headquarters", queries)
    assert posts.shares_words("Two CEOs walk into a bar", queries)  # plural of a query word
    assert not posts.shares_words("The latest news for 2026 will be good", queries)  # only filler and numbers
    assert not posts.shares_words("My GPU fans are loud", queries)


def test_feeds_are_read_one_at_a_time_and_kept_for_five_minutes():
    read = []

    async def fetch(sub):
        read.append(sub)
        if sub == "gone":
            raise RuntimeError("404")
        return FEED

    async def go():
        new = lambda sub, now: posts.subreddit_new(sub, fetch=fetch, now=now)
        assert len(await new("nvidia", 1000)) == 2
        assert await new("stocks", 1010) == [] and read == ["nvidia"]  # Reddit allows one read every half minute
        assert len(await new("nvidia", 1200)) == 2 and read == ["nvidia"]  # still fresh: not read again
        assert len(await new("stocks", 1040)) == 2 and read == ["nvidia", "stocks"]
        assert len(await new("nvidia", 1400)) == 2 and read == ["nvidia", "stocks", "nvidia"]
        assert await new("gone", 1500) == [] and await new("gone", 1600) == []  # a feed that fails is not hammered
        assert read.count("gone") == 1
        assert await new("../etc", 2000) == [] and "../etc" not in read  # not a subreddit name

    asyncio.run(go())


def test_venue_comments_that_are_replies_short_reported_or_adverts_are_trash():
    said = {"text": "Until 2028 without a new CEO? A company of NVIDIA size? Doubt it.", "is_reply": False, "reports": 0}
    assert posts.comment_trash(said) is False
    assert posts.comment_trash({**said, "is_reply": True}) is True
    assert posts.comment_trash({**said, "reports": 1}) is True
    assert posts.comment_trash({**said, "text": "add Jenson please."}) is True  # under eight words says little
    assert posts.comment_trash({**said, "text": "sbimbg locked in 12299,76 USD on Ian Buck with outcome No. We track more"}) is True
    assert posts.comment_trash({**said, "text": "all the whale data you could ever want is at https://example.com/x come see"}) is True

