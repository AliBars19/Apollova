import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { Colors } from '../constants/colors';

type BadgeStatus = 'complete' | 'failed' | 'running' | 'pending';

interface StatusBadgeProps {
  readonly status: BadgeStatus;
}

const STATUS_CONFIG: Record<BadgeStatus, { readonly label: string; readonly color: string }> = {
  complete: { label: 'Complete', color: Colors.status.green },
  failed: { label: 'Failed', color: Colors.status.danger },
  running: { label: 'Running', color: Colors.status.yellow },
  pending: { label: 'Pending', color: Colors.text.secondary },
};

export default function StatusBadge({ status }: StatusBadgeProps): React.JSX.Element {
  const config = STATUS_CONFIG[status];

  return (
    <View style={[styles.badge, { backgroundColor: config.color + '22' }]}>
      <View style={[styles.dot, { backgroundColor: config.color }]} />
      <Text style={[styles.label, { color: config.color }]}>{config.label}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  badge: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: 12,
    alignSelf: 'flex-start',
  },
  dot: {
    width: 6,
    height: 6,
    borderRadius: 3,
    marginRight: 6,
  },
  label: {
    fontSize: 12,
    fontWeight: '600',
  },
});
