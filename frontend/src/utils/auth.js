export function canCreateCompany(user) {
  return user?.role === 'admin' || user?.role === 'manager'
}

export function canCreateTeam(user) {
  return user?.role === 'admin' || user?.role === 'manager'
}
