import { useEffect, useState } from "react";
import { userStore } from "../store/userStore";

export function useAuth() {
  const [user, setUser] = useState(userStore.get());
  useEffect(() => userStore.subscribe(setUser), []);
  return { user, login: userStore.login, register: userStore.register, logout: userStore.logout, refresh: userStore.refresh };
}
