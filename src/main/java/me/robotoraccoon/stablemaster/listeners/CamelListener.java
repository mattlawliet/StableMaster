package me.robotoraccoon.stablemaster.listeners;

import me.robotoraccoon.stablemaster.StableMaster;

import java.lang.reflect.Method;
import org.bukkit.NamespacedKey;
import org.bukkit.entity.Camel;
import org.bukkit.entity.Entity;
import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.EventPriority;
import org.bukkit.event.Listener;
import org.bukkit.event.entity.EntityDamageByEntityEvent;
import org.bukkit.event.entity.EntityPortalExitEvent;
import org.bukkit.event.player.PlayerPortalEvent;
import org.bukkit.persistence.PersistentDataContainer;
import org.bukkit.persistence.PersistentDataType;

/**
 * Keeps camels from getting stuck after a dimension change.
 *
 * A camel keeps its LastPoseTick across a portal, but every Bukkit world counts
 * game time separately. Arrive in a world whose game time is lower than that
 * stamp and Camel#getPoseTime() stays negative, so Camel#isInPoseTransition()
 * is true forever: the camel refuses to move, a rider cannot stand it up, its
 * own move control cannot either, and neither can a leash.
 *
 * Vanilla's only escape is Camel#standUpInstantly, which runs when the camel
 * takes damage - and this plugin's protection cancels that damage. Standing the
 * camel up through the API re-writes the stamp using the game time of the world
 * it is actually in, which is all it needs.
 *
 * @author RobotoRaccoon
 */
public class CamelListener implements Listener {

    /** Standing up takes 52 ticks, so leave room for it before stamping again */
    private static final long RESTAMP_COOLDOWN_TICKS = 100L;

    /** Whether the pose tick could not be read, so every camel counts as stuck */
    private static boolean poseTimeUnreadable = false;

    /**
     * Camel arriving from another dimension carries a foreign game-time stamp
     * @param event Event
     */
    @EventHandler(priority = EventPriority.MONITOR, ignoreCancelled = true)
    public void onEntityPortalExit(EntityPortalExitEvent event) {
        restampNextTick(event.getEntity());
    }

    /**
     * A ridden camel travels with its rider, which reports the player, not the
     * camel. Look at what the player is sitting on once the move has happened.
     * @param event Event
     */
    @EventHandler(priority = EventPriority.MONITOR, ignoreCancelled = true)
    public void onPlayerPortal(PlayerPortalEvent event) {
        restampNextTick(event.getPlayer());
    }

    /**
     * Protection cancelled a player's punch, so run the stand-up vanilla would
     * have run. Also covers /stable release and friends, as those are punch
     * commands. Deliberately not EntityDamageEvent: a repeating source such as
     * fire or suffocation would stamp every tick and hold the camel in its pose
     * transition, which pins it exactly like the bug being fixed.
     * @param event Event
     */
    @EventHandler(priority = EventPriority.HIGHEST)
    public void onEntityDamageByEntity(EntityDamageByEntityEvent event) {
        if (event.isCancelled() && event.getDamager() instanceof Player && event.getEntity() instanceof Camel) {
            restamp((Camel) event.getEntity());
        }
    }

    /**
     * Re-stamp once the teleport has actually happened
     * @param entity Entity that travelled, or its rider
     */
    private void restampNextTick(final Entity entity) {
        StableMaster.getPlugin().getServer().getScheduler().runTask(StableMaster.getPlugin(), () -> {
            final Entity target = (entity instanceof Player) ? entity.getVehicle() : entity;
            if (target instanceof Camel) {
                restamp((Camel) target);
            }
        });
    }

    /**
     * Stand the camel up, which stamps the game time of the world it is in.
     * A camel carrying a negative stamp is sitting as far as the server is
     * concerned and standing up is enough. One carrying a positive stamp is
     * already standing, so it has to sit down before it can stand up again.
     * Neither reports itself reliably through Sittable#isSitting, so go by the
     * pose time and check whether the first attempt took.
     * @param camel Camel
     */
    private void restamp(Camel camel) {
        final Long before = poseTime(camel);

        // A pose time of zero or more is a camel using this world's clock
        if (before != null && before >= 0L) {
            return;
        }

        if (!claimStamp(camel)) {
            return;
        }

        camel.setSitting(false);

        final Long afterStandUp = poseTime(camel);
        if (afterStandUp == null || afterStandUp < 0L) {
            camel.setSitting(true);
            camel.setSitting(false);
        }

        StableMaster.getPlugin().getLogger().info("Stood up stuck camel " + camel.getUniqueId()
            + " (pose time " + before + " -> " + poseTime(camel) + ")");
    }

    /**
     * Game time elapsed since the camel's pose stamp. Negative means the stamp
     * is ahead of this world's clock, which is the bug being worked around.
     * Nothing in the Bukkit API reports it, hence the server entity.
     * @param camel Camel
     * @return Pose time, or null if it could not be read
     */
    private Long poseTime(Camel camel) {
        if (poseTimeUnreadable) {
            return null;
        }

        try {
            final Method getHandle = camel.getClass().getMethod("getHandle");
            final Object handle = getHandle.invoke(camel);
            return (Long) handle.getClass().getMethod("getPoseTime").invoke(handle);
        } catch (ReflectiveOperationException | ClassCastException e) {
            // ponytail: no API for the pose tick. Without it every camel has to
            // be treated as possibly stuck, which costs a needless sit and
            // stand. Drop this method if the API ever exposes the tick.
            poseTimeUnreadable = true;
            StableMaster.getPlugin().getLogger().warning(
                "Cannot read a camel's pose tick (" + e + "), so camels will be stood up on every punch and portal");
            return null;
        }
    }

    /**
     * Take the cooldown slot, so repeat punches cannot keep restarting the
     * stand-up animation the camel cannot move during
     * @param camel Camel
     * @return Whether the caller may stamp
     */
    private boolean claimStamp(Camel camel) {
        final long now = camel.getWorld().getGameTime();
        final NamespacedKey key = new NamespacedKey(StableMaster.getPlugin(), "last-pose-restamp");
        final PersistentDataContainer data = camel.getPersistentDataContainer();
        final Long last = data.get(key, PersistentDataType.LONG);

        // A stamp from the future is a stamp from another world's clock, which
        // is the whole problem here, so only an in-range one counts as recent.
        if (last != null && now >= last && now - last < RESTAMP_COOLDOWN_TICKS) {
            return false;
        }

        data.set(key, PersistentDataType.LONG, now);
        return true;
    }
}
