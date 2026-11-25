"""V2 任务树：单位选择、上下限、装配契约、扩缩触发。

都是纯函数，不需要模型与进程；树长不长得成由 thresholds 的资源项判。
"""
import unittest

from sa2.autonomy import tree


class ChooseUnitTest(unittest.TestCase):
    def test_low_budget_is_leaf(self):
        unit, reason = tree.choose_unit(dims=("correctness",), criteria=("c",), budget=1000)
        self.assertEqual(unit, tree.LEAF)
        self.assertIn("单人下限", reason)

    def test_multi_section_splits_when_depth_allows(self):
        unit, reason = tree.choose_unit(dims=("correctness",), criteria=("c",),
                                        budget=50000, headings=3)
        self.assertEqual(unit, tree.RECURSE)
        self.assertIn("按节拆", reason)

    def test_depth_cap_blocks_split(self):
        unit, _ = tree.choose_unit(dims=("correctness",), criteria=("c",),
                                   budget=50000, headings=3, depth=3)
        self.assertEqual(unit, tree.LEAF)

    def test_multi_dimension_is_group(self):
        unit, _ = tree.choose_unit(dims=("correctness", "security"), criteria=("c",),
                                   budget=50000)
        self.assertEqual(unit, tree.GROUP)

    def test_three_criteria_is_group(self):
        unit, _ = tree.choose_unit(dims=("correctness",), criteria=("a", "b", "c"),
                                   budget=50000)
        self.assertEqual(unit, tree.GROUP)

    def test_needs_hand_stays_single(self):
        unit, reason = tree.choose_unit(dims=("correctness",), criteria=("c",),
                                        budget=50000, needs_hand=True)
        self.assertEqual(unit, tree.LEAF)
        self.assertIn("挂手", reason)


class ExpandTest(unittest.TestCase):
    def subs(self, n):
        return [{"goal": f"子{i}", "dims": ("correctness",), "criteria": ("c",)}
                for i in range(n)]

    def test_expand_splits_budget_with_reserve(self):
        node = tree.Node("r", "目标", budget=100000, depth=0)
        children = tree.expand(node, self.subs(2))
        self.assertEqual([c.id for c in children], ["r.1", "r.2"])
        self.assertEqual(children[0].budget, 35000)   # (100000-30000)//2
        self.assertEqual(children[0].depth, 1)

    def test_fan_out_cap_raises(self):
        node = tree.Node("r", "目标", budget=100000, depth=0)
        with self.assertRaisesRegex(tree.TreeError, "扇出"):
            tree.expand(node, self.subs(13))

    def test_depth_cap_raises(self):
        node = tree.Node("r", "目标", budget=100000, depth=3)
        with self.assertRaisesRegex(tree.TreeError, "深度"):
            tree.expand(node, self.subs(2))

    def test_empty_subtasks_are_refused(self):
        node = tree.Node("r", "目标", budget=100000, depth=0)
        with self.assertRaisesRegex(tree.TreeError, "没有子任务"):
            tree.expand(node, [])


class AssembleTest(unittest.TestCase):
    def child(self, cid="c1", head="## 一、a", evidence=("S1",)):
        return tree.Node(cid, "子目标", artifact=f"{head}\n正文", evidence=evidence)

    def test_good_children_are_joined(self):
        text, problems = tree.assemble([self.child("c1"), self.child("c2", "## 二、b")])
        self.assertEqual(problems, [])
        self.assertIn("## 一、a", text)
        self.assertIn("## 二、b", text)

    def test_missing_artifact_is_reported(self):
        _, problems = tree.assemble([tree.Node("c1", "子", artifact="", evidence=("S1",))])
        self.assertTrue(any("没有产物" in p for p in problems), problems)

    def test_duplicate_heading_is_reported(self):
        _, problems = tree.assemble([self.child("c1"), self.child("c2")])
        self.assertTrue(any("标题重复" in p for p in problems), problems)

    def test_missing_evidence_is_reported(self):
        _, problems = tree.assemble([self.child("c1", evidence=())])
        self.assertTrue(any("没有证据编号" in p for p in problems), problems)


class ScalingRulesTest(unittest.TestCase):
    def test_expand_on_repeated_rejection(self):
        go, why = tree.should_expand(rejects=2, delivery_red=False,
                                     failure_kinds=["criteria_rejected"], depth=0)
        self.assertTrue(go, why)

    def test_expand_on_delivery_red(self):
        go, _ = tree.should_expand(rejects=0, delivery_red=True,
                                   failure_kinds=["unsigned_reference"], depth=1)
        self.assertTrue(go)

    def test_no_expand_at_depth_cap(self):
        go, why = tree.should_expand(rejects=5, delivery_red=True, depth=3)
        self.assertFalse(go)
        self.assertIn("深度上限", why)

    def test_contract_after_three_l2(self):
        go, why = tree.should_contract(l2_streak=3)
        self.assertTrue(go, why)

    def test_contract_on_low_efficiency(self):
        go, _ = tree.should_contract(l2_streak=0, efficiency=40)
        self.assertTrue(go)

    def test_no_contract_when_healthy(self):
        self.assertFalse(tree.should_contract(l2_streak=1, efficiency=120)[0])


if __name__ == "__main__":
    unittest.main()