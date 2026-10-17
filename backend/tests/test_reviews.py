import io
import os
import unittest
from datetime import timedelta

from PIL import Image

from tests import base
import clock
import reviews
import store

GOOD_TEXT = "The temple corridors were stunning in the early morning and the staff were very helpful."


def jpeg(size=(320, 200), exif_note=None, orientation=None, fmt="JPEG", mode="RGB"):
    im = Image.new(mode, size, (200, 120, 40) if mode == "RGB" else (200, 120, 40, 128))
    buf = io.BytesIO()
    kwargs = {}
    if exif_note or orientation:
        ex = Image.Exif()
        if exif_note:
            ex[0x010E] = exif_note                 # ImageDescription - stands in for GPS and other private metadata
        if orientation:
            ex[0x0112] = orientation
        kwargs["exif"] = ex
    im.save(buf, fmt, **kwargs)
    return buf.getvalue()


class ReviewBase(base.Base):
    def grant(self, email, place="madurai", kind="train", when="past", status="CONFIRMED"):
        today = clock.today()
        day = today if when == "past" else today + timedelta(days=3)
        rec = {"id": f"b{len(store.read()['bookings'])}", "kind": kind, "user": email, "place": place, "status": status, "date": day.isoformat()}
        if kind == "hotel":
            rec["check_in"] = (day - timedelta(days=2)).isoformat()
            rec["check_out"] = day.isoformat()
        store.read()["bookings"].append(rec)

    def traveller(self, email="a@epic.test", name="Asha Kumar", place="madurai"):
        h = self.user(email, name)
        self.grant(email, place)
        return h

    def post(self, h, place="madurai", rating=5, title="Wonderful", text=GOOD_TEXT):
        return self.c.post(f"/api/destinations/{place}/reviews", json={"rating": rating, "title": title, "text": text}, headers=h)

    def post_photos(self, h, photos, place="madurai", rating=5, text=GOOD_TEXT, **extra):
        data = {"rating": str(rating), "title": "With photos", "text": text, **extra,
                "photos": [(io.BytesIO(b), name) for b, name in photos]}
        return self.c.post(f"/api/destinations/{place}/reviews", data=data, headers=h, content_type="multipart/form-data")

    def listing(self, place="madurai", h=None, **q):
        qs = "&".join(f"{k}={v}" for k, v in q.items())
        return self.c.get(f"/api/destinations/{place}/reviews?{qs}", headers=h or {}).get_json()


class EligibilityTests(ReviewBase):
    def test_signed_out_and_no_booking_cannot_review(self):
        self.assertEqual(self.c.post("/api/destinations/madurai/reviews", json={"rating": 5, "text": GOOD_TEXT}).status_code, 401)
        h = self.user()
        r = self.post(h)
        self.assertEqual(r.status_code, 403)
        self.assertIn("Book a trip", r.get_json()["error"])
        j = self.listing(h=h)
        self.assertFalse(j["can_review"])

    def test_a_completed_trip_to_that_town_unlocks_the_review(self):
        h = self.traveller()
        self.assertTrue(self.listing(h=h)["can_review"])
        self.assertEqual(self.post(h).status_code, 201)

    def test_other_towns_do_not_count(self):
        h = self.traveller(place="ooty")
        self.assertEqual(self.post(h, place="madurai").status_code, 403)
        self.assertEqual(self.post(h, place="ooty").status_code, 201)

    def test_an_upcoming_trip_does_not_count_yet(self):
        h = self.user()
        self.grant("a@epic.test", when="future")
        r = self.post(h)
        self.assertEqual(r.status_code, 403)
        self.assertIn("once your trip is done", r.get_json()["error"])

    def test_cancelled_pending_and_expired_bookings_do_not_count(self):
        h = self.user()
        for st in ("CANCELLED", "PENDING_PAYMENT", "EXPIRED"):
            self.grant("a@epic.test", status=st)
        self.assertEqual(self.post(h).status_code, 403)

    def test_hotel_stays_count_once_they_have_ended(self):
        h = self.user()
        self.grant("a@epic.test", kind="hotel", when="past")
        self.assertEqual(self.post(h).status_code, 201)

    def test_someone_elses_booking_does_not_count(self):
        self.traveller("a@epic.test")
        b = self.user("b@epic.test", "Bala")
        self.assertEqual(self.post(b).status_code, 403)


class ValidationTests(ReviewBase):
    def test_bad_input_is_rejected(self):
        h = self.traveller()
        for label, kw in [("rating 0", {"rating": 0}), ("rating 6", {"rating": 6}), ("rating text", {"rating": "5"}), ("rating bool", {"rating": True}),
                          ("rating missing", {"rating": None}), ("too short", {"text": "Nice."}), ("blank", {"text": " " * 40}),
                          ("too long", {"text": "word " * 400}), ("long title", {"title": "T" * 81}),
                          ("a link", {"text": GOOD_TEXT + " visit www.cheap-deals.com now"}), ("a url", {"text": GOOD_TEXT + " http://x.test"}),
                          ("all caps", {"text": "THIS PLACE WAS ABSOLUTELY AMAZING AND I LOVED EVERY SECOND OF IT"}),
                          ("repeated characters", {"text": "Great place" + "a" * 20 + " and very good"}),
                          ("repeated word", {"text": "good good good good good good good good place"})]:
            r = self.post(h, **kw)
            self.assertEqual(r.status_code, 400, label)
        self.assertEqual(store.read()["reviews"], [])

    def test_the_same_text_cannot_be_pasted_across_towns(self):
        h = self.traveller(place="madurai")
        self.grant("a@epic.test", place="ooty")
        self.assertEqual(self.post(h, place="madurai").status_code, 201)
        r = self.post(h, place="ooty")
        self.assertEqual(r.status_code, 400)
        self.assertIn("already posted", r.get_json()["error"])

    def test_at_most_three_new_reviews_a_day(self):
        h = self.user()
        places = ["madurai", "ooty", "chennai", "kanyakumari"]
        for p in places:
            self.grant("a@epic.test", place=p)
        codes = [self.post(h, place=p, text=f"Visit number {i} was lovely and the food at the stalls was excellent.").status_code for i, p in enumerate(places)]
        self.assertEqual(codes, [201, 201, 201, 429])
        clock.freeze(clock.now() + timedelta(hours=25))
        self.assertEqual(self.post(h, place="kanyakumari", text="A calm morning by the sea made the whole trip worthwhile.").status_code, 201)


class ReviewLifecycleTests(ReviewBase):
    def test_one_review_per_town_and_posting_again_edits_it(self):
        h = self.traveller()
        a = self.post(h, rating=3, title="OK", text="It was fine, though the queues were really long on the day.")
        self.assertEqual(a.status_code, 201)
        rid = a.get_json()["review"]["id"]
        self.assertEqual(self.post(self.user("b@epic.test", "Bala"), place="madurai").status_code, 403)
        b = self.post(h, rating=5, title="Better on reflection", text="On reflection the architecture alone made it worth the wait.")
        self.assertEqual(b.status_code, 200)
        self.assertEqual(b.get_json()["review"]["id"], rid)
        j = self.listing(h=h)
        self.assertEqual((j["summary"]["count"], j["reviews"][0]["rating"], j["can_review"], j["can_edit"]), (1, 5, False, True))
        self.assertIsNotNone(j["reviews"][0]["edited"])

    def test_deleting_removes_the_review_and_its_photos(self):
        h = self.traveller()
        self.post_photos(h, [(jpeg(), "a.jpg")])
        name = store.read()["reviews"][0]["photos"][0]
        self.assertTrue(os.path.exists(os.path.join(store.UPLOAD_DIR, name)))
        self.assertEqual(self.c.delete("/api/destinations/madurai/reviews/mine", headers=h).status_code, 200)
        self.assertFalse(os.path.exists(os.path.join(store.UPLOAD_DIR, name)))
        self.assertEqual(self.listing()["summary"]["count"], 0)
        self.assertEqual(self.c.delete("/api/destinations/madurai/reviews/mine", headers=h).status_code, 404)

    def test_names_are_shortened_for_privacy(self):
        self.assertEqual(reviews.display_name("x@e.test"), "x")
        h = self.traveller(name="Asha Kumar")
        self.post(h)
        self.assertEqual(self.listing()["reviews"][0]["name"], "Asha K.")
        self.assertNotIn("a@epic.test", str(self.listing()))                      # the email is never exposed
        self.user("m@epic.test", "Madonna")
        store.read()["users"]["m@epic.test"]["name"] = "Madonna"
        self.assertEqual(reviews.display_name("m@epic.test"), "Madonna")

    def test_summary_uses_a_bayesian_average_and_a_distribution(self):
        for i, rating in enumerate([5, 4, 4, 2]):
            h = self.traveller(f"u{i}@epic.test", f"User {i}")
            self.post(h, rating=rating, text=f"Review number {i} with enough words to be accepted by the filter.")
        s = self.listing()["summary"]
        self.assertEqual((s["count"], s["average"]), (4, 3.8))
        self.assertAlmostEqual(s["score"], round((5 * 4.0 + 15) / 9, 2))
        self.assertEqual(s["distribution"], {"1": 0, "2": 1, "3": 0, "4": 2, "5": 1})
        self.assertIsNone(self.listing("ooty")["summary"]["average"])

    def test_one_five_star_review_does_not_beat_many_good_ones(self):
        one = self.traveller("solo@epic.test", "Solo")
        self.post(one, place="madurai", rating=5)
        for i in range(10):
            self.traveller(f"n{i}@epic.test", f"N {i}", place="ooty")
            h = {"Authorization": "Bearer " + self.c.post("/api/auth/login", json={"email": f"n{i}@epic.test", "password": "longenough1"}).get_json()["token"]}
            self.post(h, place="ooty", rating=4, text=f"Visit {i} was pleasant and the views at the top were great.")
        self.assertGreater(self.listing("ooty")["summary"]["score"], self.listing("madurai")["summary"]["score"] - 0.2)
        self.assertLess(self.listing("madurai")["summary"]["score"], 5.0)

    def test_sorting_by_helpful_and_by_newest(self):
        voters = [self.user(f"v{i}@epic.test", f"Voter {i}") for i in range(2)]
        ids = []
        for i in range(3):
            h = self.traveller(f"w{i}@epic.test", f"Writer {i}")
            clock.freeze(clock.now() + timedelta(minutes=10))
            ids.append(self.post(h, text=f"Writer number {i} has quite a lot to say about the visit.").get_json()["review"]["id"])
        for v in voters:
            self.c.post(f"/api/reviews/{ids[0]}/helpful", headers=v)
        self.assertEqual([r["id"] for r in self.listing(sort="helpful")["reviews"]][0], ids[0])
        self.assertEqual([r["id"] for r in self.listing(sort="newest")["reviews"]], ids[::-1])

    def test_paging(self):
        for i in range(5):
            self.post(self.traveller(f"p{i}@epic.test", f"P {i}"), text=f"Paging check number {i} with a fair amount of detail here.")
        a, b = self.listing(limit=2, offset=0, sort="newest"), self.listing(limit=2, offset=2, sort="newest")
        self.assertEqual((len(a["reviews"]), len(b["reviews"]), a["total"]), (2, 2, 5))
        self.assertFalse({r["id"] for r in a["reviews"]} & {r["id"] for r in b["reviews"]})


class PhotoTests(ReviewBase):
    def stored(self):
        return [os.path.join(store.UPLOAD_DIR, n) for r in store.read()["reviews"] for n in r["photos"]]

    @staticmethod
    def image_info(path):
        with Image.open(path) as im:
            return im.size, im.format

    def test_photos_are_re_encoded_and_their_metadata_is_dropped(self):
        h = self.traveller()
        raw = jpeg(exif_note="SECRET-GPS-NOTE")
        self.assertIn(b"SECRET-GPS-NOTE", raw)
        r = self.post_photos(h, [(raw, "holiday.jpg")])
        self.assertEqual(r.status_code, 201, r.get_json())
        path = self.stored()[0]
        with open(path, "rb") as fh:
            data = fh.read()
        self.assertNotIn(b"SECRET-GPS-NOTE", data)
        with Image.open(path) as im:
            self.assertEqual(im.format, "JPEG")
            self.assertEqual(len(im.getexif()), 0)

    def test_phone_rotation_is_applied_before_the_metadata_goes(self):
        h = self.traveller()
        self.post_photos(h, [(jpeg(size=(200, 100), orientation=6), "p.jpg")])
        self.assertEqual(self.image_info(self.stored()[0])[0], (100, 200))

    def test_large_images_are_scaled_down_and_other_formats_are_converted(self):
        h = self.traveller()
        self.post_photos(h, [(jpeg(size=(3200, 2400)), "big.jpg"), (jpeg(size=(300, 300), fmt="PNG", mode="RGBA"), "a.png")])
        infos = [self.image_info(p) for p in self.stored()]
        self.assertEqual(max(infos[0][0]), 1600)
        self.assertTrue(all(fmt == "JPEG" for _, fmt in infos))

    def test_files_that_are_not_images_are_refused(self):
        h = self.traveller()
        gif = io.BytesIO()
        Image.new("P", (10, 10)).save(gif, "GIF")
        for label, blob in [("text renamed .jpg", b"hello, I am definitely a picture"), ("empty", b""), ("gif", gif.getvalue()),
                            ("truncated jpeg", jpeg(size=(800, 800))[:300]), ("html", b"<script>alert(1)</script>")]:
            r = self.post_photos(h, [(blob, "x.jpg")])
            self.assertEqual(r.status_code, 400, label)
        self.assertEqual((self.stored(), store.read()["reviews"]), ([], []))

    def test_at_most_three_photos_and_one_bad_photo_rejects_the_whole_review(self):
        h = self.traveller()
        self.assertEqual(self.post_photos(h, [(jpeg(), f"{i}.jpg") for i in range(4)]).status_code, 400)
        self.assertEqual(self.post_photos(h, [(jpeg(), "ok.jpg"), (b"junk", "bad.jpg")]).status_code, 400)
        self.assertEqual((self.stored(), store.read()["reviews"]), ([], []))
        self.assertEqual(self.post_photos(h, [(jpeg(), f"{i}.jpg") for i in range(3)]).status_code, 201)

    def test_oversized_files_are_refused(self):
        h = self.traveller()
        r = self.post_photos(h, [(b"\xff\xd8" + b"0" * (reviews.MAX_PHOTO_BYTES + 10), "huge.jpg")])
        self.assertEqual(r.status_code, 400)
        self.assertIn("MB", r.get_json()["error"])
        r = self.post_photos(h, [(b"0" * (19 * 1024 * 1024), "enormous.jpg")])
        self.assertEqual(r.status_code, 413)

    def test_uploads_are_served_safely(self):
        h = self.traveller()
        self.post_photos(h, [(jpeg(), "a.jpg")])
        url = self.listing()["reviews"][0]["photos"][0]
        r = self.c.get(url)
        self.assertEqual((r.status_code, r.mimetype), (200, "image/jpeg"))
        self.assertEqual(r.headers["X-Content-Type-Options"], "nosniff")
        r.close()
        for bad in ("../store.json", "..%2fstore.json", "..%5cstore.json", "x.jpg", "a" * 32 + ".jpg", "a" * 32 + ".html", ".." + "a" * 30 + ".jpg"):
            self.assertEqual(self.c.get(f"/api/uploads/{bad}").status_code, 404, bad)

    def test_editing_can_replace_or_remove_photos_and_old_files_are_deleted(self):
        h = self.traveller()
        self.post_photos(h, [(jpeg(), "a.jpg"), (jpeg(), "b.jpg")])
        old = self.stored()
        self.post_photos(h, [(jpeg(size=(50, 50)), "c.jpg")])
        self.assertEqual(len(self.stored()), 1)
        self.assertTrue(all(not os.path.exists(p) for p in old))
        self.post_photos(h, [], remove_photos="1")
        self.assertEqual(self.stored(), [])


class VotesAndModerationTests(ReviewBase):
    def setUp(self):
        super().setUp()
        self.author = self.traveller("author@epic.test", "Author One")
        self.rid = self.post(self.author).get_json()["review"]["id"]
        self.readers = [self.user(f"r{i}@epic.test", f"Reader {i}") for i in range(4)]
        self.admin = self.user("admin@epic.test", "Admin")

    def test_helpful_is_a_per_person_toggle_and_not_for_your_own_review(self):
        r0 = self.readers[0]
        self.assertEqual(self.c.post(f"/api/reviews/{self.rid}/helpful", headers=r0).get_json(), {"helpful": 1, "voted": True})
        self.assertEqual(self.c.post(f"/api/reviews/{self.rid}/helpful", headers=self.readers[1]).get_json()["helpful"], 2)
        self.assertEqual(self.c.post(f"/api/reviews/{self.rid}/helpful", headers=r0).get_json(), {"helpful": 1, "voted": False})
        self.assertEqual(self.c.post(f"/api/reviews/{self.rid}/helpful", headers=self.author).status_code, 400)
        self.assertEqual(self.c.post(f"/api/reviews/{self.rid}/helpful").status_code, 401)
        self.assertEqual(self.c.post("/api/reviews/rev_nope/helpful", headers=r0).status_code, 404)
        self.assertTrue(self.listing(h=r0)["reviews"][0]["voted"] is False)

    def report(self, h, reason="spam"):
        return self.c.post(f"/api/reviews/{self.rid}/report", json={"reason": reason}, headers=h)

    def test_three_different_reporters_hide_a_review_but_one_person_cannot(self):
        for _ in range(5):
            self.report(self.readers[0])
        self.assertEqual(self.listing()["summary"]["count"], 1, "one person reporting repeatedly must not hide a review")
        self.report(self.readers[1])
        r = self.report(self.readers[2]).get_json()
        self.assertTrue(r["hidden"])
        self.assertEqual(self.listing()["reviews"], [])
        self.assertEqual(self.listing()["summary"]["count"], 0)                    # and it no longer counts toward the rating
        self.assertEqual(self.listing(h=self.author)["mine"]["status"], "flagged")  # the author is told
        self.assertEqual(self.report(self.author).status_code, 400)

    def flag(self):
        for r in self.readers[:3]:
            self.report(r)

    def test_the_moderation_queue_is_for_admins_only(self):
        self.flag()
        for h in (self.author, self.readers[0]):
            self.assertEqual(self.c.get("/api/admin/reviews", headers=h).status_code, 403)
            self.assertEqual(self.c.post(f"/api/admin/reviews/{self.rid}/approve", headers=h).status_code, 403)
        self.assertEqual(self.c.get("/api/admin/reviews").status_code, 401)
        q = self.c.get("/api/admin/reviews", headers=self.admin).get_json()
        self.assertEqual((len(q), q[0]["id"], len(q[0]["reports"])), (1, self.rid, 3))

    def test_admin_can_restore_a_review(self):
        self.flag()
        self.assertEqual(self.c.post(f"/api/admin/reviews/{self.rid}/approve", headers=self.admin).get_json()["status"], "visible")
        self.assertEqual(self.listing()["summary"]["count"], 1)
        self.report(self.readers[0])                                                # earlier reports were cleared
        self.assertEqual(self.listing()["summary"]["count"], 1)

    def test_admin_can_remove_a_review_and_its_photos(self):
        self.c.delete("/api/destinations/madurai/reviews/mine", headers=self.author)
        self.post_photos(self.author, [(jpeg(), "a.jpg")])
        rev = store.read()["reviews"][0]
        path = os.path.join(store.UPLOAD_DIR, rev["photos"][0])
        for r in self.readers[:3]:
            self.c.post(f"/api/reviews/{rev['id']}/report", json={}, headers=r)
        self.assertEqual(self.c.post(f"/api/admin/reviews/{rev['id']}/remove", headers=self.admin).get_json()["status"], "removed")
        self.assertFalse(os.path.exists(path))
        self.assertEqual(self.listing()["summary"]["count"], 0)
        self.assertEqual(self.c.post(f"/api/admin/reviews/{rev['id']}/explode", headers=self.admin).status_code, 400)
        self.assertEqual(self.c.post(f"/api/reviews/{rev['id']}/helpful", headers=self.readers[3]).status_code, 404)


if __name__ == "__main__":
    unittest.main()
