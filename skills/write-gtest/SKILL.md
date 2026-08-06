---
name: write-gtest
description: >
  Use when the user asks to write unit tests, add test coverage, review existing unit tests,
  or improve a test file. Auto-triggered when: a file ending in _test.cc, _test.cpp, _unittest.cc,
  or test_*.cc is opened for review or editing; the user says "write a test for X", "add unit tests",
  "review this test", "what's wrong with this test", or "how should I test X".
version: 1.0.0
user-invocable: true
---

# Write Google Test Unit Tests

Write C++ unit tests using [GoogleTest](https://google.github.io/googletest/).

## Rules

1. Use snake_case for test fixtures and test names. Structure test names clarifying if it is testing a function/method or cause-effects. e.g.
```cpp
TEST_F(byte_buffer_test, shallow_copy) { ... }
TEST(circular_buffer_test, when_buffer_is_empty_then_pop_returns_nullopt) { ... }
TEST_F(scheduler_test, when_queue_is_full_then_packet_is_dropped) { ... }
```
2. Never use `EXPECT_*`. Always use `ASSERT_*`.
3. When multiple tests share the same setup, use a `TEST_F` or `TEST_P` fixture instead of repeating the setup in each test body:
4. Minimize the use of magic numbers. Use static constexpr variables with the names that are clear enough to express what these numbers represent.
5. Before writing a new fixture, check whether an existing base tester class covers the setup and can be reused. Search the surrounding test files for classes like `base_scheduler_tdd_tester`; new fixtures often derive from them, e.g.
```cpp
class scheduler_dl_tdd_tester : public base_scheduler_tdd_tester, public ::testing::TestWithParam<tdd_test_params> { ... };
```
Prefer extending or composing the base tester over duplicating its setup.
