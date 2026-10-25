/* eslint-env jest */
// SecureStore is a native module; give it an in-memory implementation so the
// API layer can be exercised in the test environment.
jest.mock("expo-secure-store", () => {
  const store = new Map();
  return {
    getItemAsync: jest.fn(async key => (store.has(key) ? store.get(key) : null)),
    setItemAsync: jest.fn(async (key, value) => { store.set(key, value); }),
    deleteItemAsync: jest.fn(async key => { store.delete(key); }),
    __store: store,
  };
});

// Icon fonts pull in expo-asset, which Jest's resolver cannot see because it is
// nested under expo/node_modules. Icons are irrelevant to behaviour tests.
jest.mock("@expo/vector-icons", () => {
  const React = require("react");
  const { View } = require("react-native");
  const Icon = () => React.createElement(View);
  return { Ionicons: Icon };
});
