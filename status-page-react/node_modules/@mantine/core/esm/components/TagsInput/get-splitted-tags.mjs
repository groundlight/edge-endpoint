'use client';
function splitTags(splitChars, value) {
  if (!splitChars) {
    return [value];
  }
  return value.split(new RegExp(`[${splitChars.join("")}]`)).map((tag) => tag.trim()).filter((tag) => tag !== "");
}
function getSplittedTags({
  splitChars,
  allowDuplicates,
  maxTags,
  value,
  currentTags,
  isDuplicate,
  onDuplicate
}) {
  const splitted = splitTags(splitChars, value);
  const merged = [];
  if (allowDuplicates) {
    merged.push(...currentTags, ...splitted);
  } else {
    merged.push(...currentTags);
    for (const tag of splitted) {
      const checkDuplicate = isDuplicate ? (val) => isDuplicate(val, merged) : (val) => merged.some((t) => t.toLowerCase() === val.toLowerCase());
      if (checkDuplicate(tag)) {
        onDuplicate?.(tag);
      } else {
        merged.push(tag);
      }
    }
  }
  return maxTags ? merged.slice(0, maxTags) : merged;
}

export { getSplittedTags };
//# sourceMappingURL=get-splitted-tags.mjs.map
