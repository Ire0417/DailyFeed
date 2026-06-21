import { create } from "zustand";
import type { Subscription } from "../types/subscription";

interface SubscriptionState {
  items: Subscription[];
  setItems: (items: Subscription[]) => void;
  add: (item: Subscription) => void;
  remove: (id: number) => void;
}

export const useSubscriptionStore = create<SubscriptionState>((set) => ({
  items: [],
  setItems: (items) => set({ items }),
  add: (item) => set((state) => ({ items: [...state.items, item] })),
  remove: (id) => set((state) => ({ items: state.items.filter((i) => i.id !== id) })),
}));
